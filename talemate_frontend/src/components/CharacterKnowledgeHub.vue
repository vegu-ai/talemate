<template>
    <v-menu v-model="open" :close-on-content-click="false" location="bottom" max-width="400" min-width="340" @update:model-value="onToggle">
        <template v-slot:activator="{ props: menuProps }">
            <v-tooltip :text="`Knowledge of ${name}`">
                <template v-slot:activator="{ props: tooltipProps }">
                    <v-btn
                        v-bind="{ ...menuProps, ...tooltipProps }"
                        :aria-label="`Knowledge of ${name}`"
                        size="x-small"
                        class="mr-1 knowledge-hub-activator"
                        :variant="variant"
                        :color="color"
                        density="comfortable"
                        rounded="sm"
                        icon="mdi-head-lightbulb-outline"
                        @click.stop></v-btn>
                </template>
            </v-tooltip>
        </template>

        <v-card class="knowledge-hub" density="compact">
            <v-card-item class="pb-1">
                <v-card-title class="text-title-small d-flex align-center pa-0">
                    <v-icon size="small" class="mr-1">mdi-head-lightbulb-outline</v-icon>
                    {{ name }}
                    <v-spacer></v-spacer>
                    <v-chip size="x-small" label variant="tonal" :color="perspectives ? 'primary' : 'mutedheader'">{{ summary.mode }}</v-chip>
                </v-card-title>
            </v-card-item>

            <!-- WHAT THE CHARACTER KNOWS -->

            <v-card-subtitle class="text-uppercase pt-2">What {{ name }} knows</v-card-subtitle>
            <v-card-text class="pt-2 pb-2">
                <v-progress-linear v-if="loading" indeterminate color="primary" height="2"></v-progress-linear>
                <template v-else-if="knowledge">
                    <div v-if="knowledge.known_facts.length">
                        <div v-for="fact in knowledge.known_facts" :key="fact.id" class="text-body-small py-1 knowledge-hub-fact">
                            <span v-if="fact.topic" class="text-mutedheader mr-1">{{ fact.topic }}:</span>{{ fact.text }}
                        </div>
                    </div>
                    <a href="#" class="text-body-small text-muted d-block knowledge-hub-count" @click.prevent="openKnowledge">{{ factsCount }}</a>
                    <div v-if="!knowledge.perception_mode && knowledge.awareness" class="text-body-small text-muted mt-1">{{ knowledge.awareness }}.</div>

                    <div class="text-body-small text-mutedheader mt-2">
                        {{ knowledge.perception_mode ? 'Disclosures' : 'Entry access rules' }} ({{ entriesTotal }})
                    </div>
                    <div v-if="entries.length">
                        <div v-for="entry in entries" :key="entry.id" class="d-flex align-center text-body-small py-1">
                            <v-chip v-if="entry.kind" size="x-small" label variant="tonal" class="mr-2 flex-shrink-0" :color="entry.kind === 'grant' ? 'success' : 'delete'">
                                {{ entry.kind === 'grant' ? 'Allow' : 'Block' }}
                            </v-chip>
                            <span class="knowledge-hub-entry">{{ entry.text }}</span>
                        </div>
                        <div v-if="entriesTotal > entries.length" class="text-body-small text-muted">{{ entries.length }} most recent shown.</div>
                    </div>
                    <div v-else class="text-body-small text-muted">
                        {{ knowledge.perception_mode ? 'Nothing has been disclosed by hand.' : 'No rules. Knowledge follows presence, ownership and sharing.' }}
                    </div>
                </template>
                <v-btn size="x-small" variant="text" color="primary" class="mt-2" prepend-icon="mdi-book-open-page-variant" @click="openKnowledge">Open Knowledge tab</v-btn>
            </v-card-text>

            <v-divider></v-divider>

            <!-- STORY MODE -->

            <v-card-subtitle class="text-uppercase pt-3">Story mode</v-card-subtitle>
            <v-card-text class="pt-0 pb-2">
                <v-switch
                    :model-value="perspectives"
                    :disabled="!canChange"
                    label="Character perspectives"
                    color="primary"
                    density="compact"
                    :hint="canChange ? PERSPECTIVES_OPEN_HINT : PERSPECTIVES_LOCKED_HINT"
                    persistent-hint
                    @update:model-value="setPerspectives"></v-switch>
                <CharacterKnowledgeModeComparison :perspectives="perspectives" selected-label="current" collapsed stacked class="mt-2" />
            </v-card-text>

            <v-divider></v-divider>

            <!-- THOROUGHNESS -->

            <v-card-subtitle class="text-uppercase pt-3">Thoroughness</v-card-subtitle>
            <v-card-text class="pt-1 pb-0">
                <KnowledgeEffortSlider :mode="effortMode" :agents="getAgents()" @apply="applyEffort" />
            </v-card-text>
            <v-card-text class="pt-1 pb-0 text-body-small text-muted">{{ summary.text }}</v-card-text>
            <v-card-text v-if="!groups.length" class="pt-1 text-body-small text-muted">Waiting for the agents to report.</v-card-text>
            <template v-for="group in groups" :key="group.agent + '.' + group.action">
                <!-- the header is a list row like the toggles under it, so both take
                     Vuetify's prepend spacing; a group without a master keeps an
                     invisible checkbox so its label lands on the same x -->
                <v-list density="compact" class="py-0 mt-1">
                    <v-list-item density="compact" class="knowledge-hub-group">
                        <template v-slot:prepend>
                            <v-checkbox-btn
                                v-if="group.master"
                                :model-value="group.enabled"
                                :aria-label="`${group.label} on or off`"
                                density="compact"
                                color="primary"
                                hide-details
                                @click.stop="toggleGroup(group)"></v-checkbox-btn>
                            <v-checkbox-btn v-else class="knowledge-hub-checkbox-placeholder" density="compact" hide-details aria-hidden="true" tabindex="-1" disabled></v-checkbox-btn>
                        </template>
                        <v-list-item-title class="text-body-small">
                            <v-btn size="x-small" variant="text" class="px-0 text-body-small" append-icon="mdi-open-in-new" @click="openSettings(group)">
                                {{ group.agentLabel }} / {{ group.label }}
                            </v-btn>
                            <v-chip v-if="group.master && group.enabledOverridden" size="x-small" label variant="outlined" color="secondary" class="ml-1">scene override</v-chip>
                        </v-list-item-title>
                    </v-list-item>
                    <!-- not :disabled - Vuetify drops pointer events on a disabled item, which
                         takes the tooltips with it; the checkbox and the click guard carry the state -->
                    <v-list-item
                        v-for="toggle in group.toggles"
                        :key="toggle.key"
                        density="compact"
                        class="knowledge-hub-toggle"
                        :class="{ 'knowledge-hub-toggle-off': !group.enabled }"
                        v-bind="group.enabled ? { onClick: () => toggleConfig(group, toggle) } : {}">
                        <template v-slot:prepend>
                            <v-checkbox-btn :model-value="toggle.value" :disabled="!group.enabled" :aria-label="toggle.label" tabindex="-1" density="compact" color="primary" hide-details @click.stop="toggleConfig(group, toggle)"></v-checkbox-btn>
                        </template>
                        <v-list-item-title class="text-body-small">
                            {{ toggle.label }}
                            <v-chip v-if="toggle.overridden" size="x-small" label variant="outlined" color="secondary" class="ml-1">scene override</v-chip>
                        </v-list-item-title>
                        <template v-slot:append>
                            <v-tooltip v-if="toggle.costNote" :text="toggle.costNote" max-width="320" location="start">
                                <template v-slot:activator="{ props: costProps }">
                                    <v-icon v-bind="costProps" size="small" color="primary" class="mr-1" tabindex="0" role="img" aria-label="Adds a request">mdi-plus-circle-outline</v-icon>
                                </template>
                            </v-tooltip>
                            <v-tooltip :text="toggle.description" max-width="320" location="start">
                                <template v-slot:activator="{ props: infoProps }">
                                    <v-icon v-bind="infoProps" size="small" color="muted" tabindex="0" role="img" aria-label="About this option">mdi-information-outline</v-icon>
                                </template>
                            </v-tooltip>
                        </template>
                    </v-list-item>
                </v-list>
            </template>
            <div class="pb-2"></div>
        </v-card>
    </v-menu>
</template>

<script>
import CharacterKnowledgeModeComparison from './CharacterKnowledgeModeComparison.vue';
import KnowledgeEffortSlider from './KnowledgeEffortSlider.vue';
import { effortMode, effortPatch, queueEffortAcrossSwitch } from '@/utils/knowledgeEffort';
import { effectiveActionEnabled } from '@/constants/sceneAgentSettings';
import { resolveKnowledgeToggles, thoroughnessSummary } from '@/utils/knowledgeHub';
import {
    PERSPECTIVES_LOCKED_HINT,
    PERSPECTIVES_OPEN_HINT,
    canChangePerspectives,
    perspectivesEnabled,
    perspectivesPayload,
} from '@/utils/sceneSettings';

const ENTRY_LIMIT = 5;

export default {
    name: 'CharacterKnowledgeHub',
    components: { CharacterKnowledgeModeComparison, KnowledgeEffortSlider },
    props: {
        name: { type: String, required: true },
        variant: { type: String, default: 'tonal' },
        color: { type: String, default: undefined },
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'scene',
        'getAgents',
        'toggleAgentAction',
        'toggleAgentConfig',
        'applyAgentValues',
        'queueKnowledgeEffort',
        'openAgentSettings',
    ],
    emits: ['open-knowledge'],
    data() {
        return {
            PERSPECTIVES_LOCKED_HINT,
            PERSPECTIVES_OPEN_HINT,
            open: false,
            loading: false,
            knowledge: null,
            topicsSeen: true,
        };
    },
    computed: {
        sceneData() {
            return this.scene ? this.scene()?.data : null;
        },
        perspectives() {
            return perspectivesEnabled(this.sceneData);
        },
        canChange() {
            return canChangePerspectives(this.sceneData);
        },
        effortMode() {
            return effortMode(this.perspectives);
        },
        groups() {
            return resolveKnowledgeToggles(this.getAgents(), { perspectives: this.perspectives });
        },
        summary() {
            return thoroughnessSummary(this.groups, this.perspectives);
        },
        // an agent that has not reported yet is taken as on
        topicsOn() {
            const topics = this.groups.find((group) => group.agent === 'memory' && group.action === 'topics');
            return topics ? topics.enabled : true;
        },
        // One list for both modes: a disclosure is what was given, a rule is
        // what was allowed or blocked. The record lists them oldest first.
        allEntries() {
            if (!this.knowledge) return [];
            if (this.knowledge.perception_mode) {
                return this.knowledge.disclosures.map((disclosure) => ({
                    id: disclosure.id,
                    kind: null,
                    text: disclosure.text,
                }));
            }
            const labels = new Map(this.knowledge.targets.map((target) => [target.id, target.label]));
            return this.knowledge.edges.map((edge) => ({
                id: edge.id,
                kind: edge.kind,
                text: labels.get(edge.target) || edge.target,
            }));
        },
        entries() {
            return this.allEntries.slice(-ENTRY_LIMIT).reverse();
        },
        entriesTotal() {
            return this.allEntries.length;
        },
        factsCount() {
            const total = this.knowledge?.known_facts_total || 0;
            if (!total) return 'No known facts yet.';
            const shown = this.knowledge.known_facts.length;
            return shown < total ? `${shown} of ${total} known facts, newest first.` : `${total} known fact${total === 1 ? '' : 's'}.`;
        },
    },
    watch: {
        // the record's shape follows the scene mode
        perspectives() {
            if (this.open) this.request();
        },
    },
    methods: {
        // both leave the panel for another view; an open menu would linger over it
        openKnowledge() {
            this.open = false;
            this.$emit('open-knowledge');
        },
        openSettings(group) {
            this.open = false;
            this.openAgentSettings(group.agent, group.action);
        },
        onToggle(opened) {
            if (!opened) return;
            this.topicsSeen = this.topicsOn;
            this.request();
        },
        request() {
            if (!this.knowledge) this.loading = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_knowledge',
                name: this.name,
            }));
        },
        setPerspectives(enabled) {
            const payload = perspectivesPayload(this.sceneData, enabled);
            if (!payload) return false;
            queueEffortAcrossSwitch(this.getAgents(), enabled, this.queueKnowledgeEffort);
            this.getWebsocket().send(JSON.stringify(payload));
            return true;
        },
        applyEffort(stop) {
            for (const entry of effortPatch(this.getAgents(), this.effortMode, stop)) {
                this.applyAgentValues(entry.agent, entry.action, entry);
            }
        },
        toggleGroup(group) {
            return this.toggleAgentAction(group.agent, group.action);
        },
        toggleConfig(group, toggle) {
            if (!group.enabled) return false;
            return this.toggleAgentConfig(group.agent, group.action, toggle.key);
        },
        handleMessage(data) {
            if (data.type === 'system' && data.id === 'scene.loaded') {
                this.knowledge = null;
                this.loading = false;
                return;
            }
            // the topic labels and the awareness line follow the Memory agent's
            // Topics switch, and its status echoes after the backend applied it
            if (data.type === 'agent_status' && data.name === 'memory') {
                const actions = data.data?.actions || {};
                const on = effectiveActionEnabled(actions, data.data?.scene_overrides || {}, 'topics');
                if (this.open && on !== this.topicsSeen) this.request();
                this.topicsSeen = on;
                return;
            }
            if (data.type === 'knowledge_changed') {
                const mine = (data.data?.changes || []).some((change) => change.character === this.name);
                if (this.open && mine) this.request();
                return;
            }
            if (data.type !== 'world_state_manager' || data.action !== 'character_knowledge') return;
            if (data.data?.name !== this.name) return;
            this.knowledge = data.data;
            this.loading = false;
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    beforeUnmount() {
        this.unregisterMessageHandler(this.handleMessage);
    },
};
</script>

<style scoped>
.knowledge-hub-checkbox-placeholder {
    visibility: hidden;
}
.knowledge-hub-toggle {
    padding-inline-start: 40px;
}
.knowledge-hub-fact {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.knowledge-hub-toggle-off :deep(.v-list-item-title) {
    opacity: var(--v-disabled-opacity);
}
.knowledge-hub-entry {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
</style>
