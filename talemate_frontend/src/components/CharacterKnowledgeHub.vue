<template>
    <v-menu v-model="open" :close-on-content-click="false" :persistent="pendingSave" location="bottom" max-width="400" min-width="340" @update:model-value="onToggle">
        <template v-slot:activator="{ props: menuProps }">
            <slot name="activator" :props="menuProps">
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
            </slot>
        </template>

        <v-card class="knowledge-hub" density="compact">
            <v-card-item class="pb-1">
                <v-card-title class="text-title-small d-flex align-center pa-0">
                    <v-icon size="small" class="mr-1">mdi-head-lightbulb-outline</v-icon>
                    {{ title }}
                    <v-spacer></v-spacer>
                    <v-chip v-if="canChange" size="x-small" label variant="tonal" :color="perspectives ? 'primary' : 'mutedheader'">{{ summary.mode }}</v-chip>
                </v-card-title>
            </v-card-item>

            <!-- WHAT THE CHARACTER KNOWS -->

            <template v-if="name">
                <v-card-subtitle class="text-uppercase pt-2">What {{ name }} knows</v-card-subtitle>
                <v-card-text class="pt-2 pb-2">
                    <v-progress-linear v-if="loading" indeterminate color="primary" height="2"></v-progress-linear>
                    <template v-else-if="knowledge">
                        <div class="text-body-small text-mutedheader mt-2">
                            {{ knowledge.perception_mode ? 'Disclosures' : 'Entry access rules' }} ({{ entriesTotal }})
                        </div>
                        <div v-if="entries.length">
                            <div v-for="entry in entries" :key="entry.id" class="d-flex align-center text-body-small py-1">
                                <v-chip v-if="entry.kind" size="x-small" label variant="tonal" class="mr-2 flex-shrink-0" :color="rules[entry.kind]?.color">
                                    {{ rules[entry.kind]?.label }}
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
            </template>

            <!-- STORY MODE -->

            <v-card-subtitle class="text-uppercase pt-3">Story mode</v-card-subtitle>
            <v-card-text class="pt-0 pb-2">
                <template v-if="canChange">
                    <v-switch
                        :model-value="perspectives"
                        label="Character perspectives"
                        color="primary"
                        density="compact"
                        :disabled="saving"
                        :hint="PERSPECTIVES_OPEN_HINT"
                        persistent-hint
                        @update:model-value="setPerspectives"></v-switch>
                    <CharacterKnowledgeModeComparison :perspectives="perspectives" selected-label="current" compact class="mt-2" />
                </template>
                <v-alert v-else color="primary" variant="tonal" density="compact" icon="mdi-lock-outline" class="mt-1 knowledge-mode-locked">
                    {{ summary.mode }} is locked for this scene because it already has history.
                </v-alert>
            </v-card-text>

            <v-divider></v-divider>

            <!-- THOROUGHNESS -->

            <v-card-subtitle class="text-uppercase pt-3">Thoroughness</v-card-subtitle>
            <v-card-text class="pt-1 pb-0">
                <div class="d-flex align-center mb-1">
                    <SceneOverrideResetControl
                        v-if="hubOverridden"
                        label="Scene override"
                        aria-label="Use global settings for all character knowledge settings"
                        :disabled="settingsLocked"
                        @reset="clearHub" />
                    <v-tooltip v-else :text="effortOriginTooltip" location="top" max-width="320">
                        <template v-slot:activator="{ props: originProps }">
                            <v-chip v-bind="originProps" size="x-small" label variant="outlined" color="muted">Global settings</v-chip>
                        </template>
                    </v-tooltip>
                </div>
                <KnowledgeEffortSlider :mode="effortMode" :agents="getAgents()" :pin="true" :disabled="settingsLocked" @apply="applyEffort" />
            </v-card-text>
            <v-card-text v-if="pendingSave" class="pt-1 pb-0">
                <KnowledgePendingSave />
            </v-card-text>
            <v-card-text v-if="saveError" class="pt-1 pb-0 text-body-small text-error">{{ saveError }}</v-card-text>
            <v-card-text v-if="!groups.length" class="pt-1 text-body-small text-muted">Waiting for the agents to report.</v-card-text>
            <v-expansion-panels v-else :model-value="individualOpen" variant="accordion" class="knowledge-hub-individual mt-1" @update:model-value="setIndividualOpen">
                <v-expansion-panel value="individual">
                    <v-expansion-panel-title class="text-body-small">
                        Individual settings
                        <span class="text-muted ml-1">&middot; {{ tally.on }} of {{ tally.total }} on</span>
                    </v-expansion-panel-title>
                    <v-expansion-panel-text>
                        <template v-for="group in groups" :key="group.agent + '.' + group.action">
                            <div class="knowledge-hub-section mt-1">
                                <div class="knowledge-hub-group d-flex align-center px-4">
                                    <div class="text-body-small knowledge-setting-label flex-grow-1">
                                        <v-btn size="x-small" variant="text" class="px-0 text-body-small" append-icon="mdi-open-in-new" @click="openSettings(group)">
                                            {{ group.agentLabel }} / {{ group.label }}
                                        </v-btn>
                                        <SceneOverrideResetControl
                                            v-if="group.ownedOverridden"
                                            :aria-label="`Use global settings for ${group.agentLabel} / ${group.label}`"
                                            :disabled="settingsLocked"
                                            @reset="clearGroup(group)" />
                                    </div>
                                    <v-checkbox-btn
                                        v-if="group.master"
                                        :model-value="group.enabled"
                                        :disabled="settingsLocked"
                                        :aria-label="`${group.label} on or off`"
                                        density="compact"
                                        color="primary"
                                        hide-details
                                        @click.stop="toggleGroup(group)"></v-checkbox-btn>
                                </div>
                                <v-list v-if="group.toggles.length" density="compact" class="py-0">
                                    <!-- not :disabled - Vuetify drops pointer events on a disabled item, which
                                         takes the tooltips with it; the checkbox and the click guard carry the state -->
                                    <v-list-item
                                        v-for="toggle in group.toggles"
                                        :key="toggle.key"
                                        density="compact"
                                        class="knowledge-hub-toggle"
                                        :class="{ 'knowledge-hub-toggle-off': !group.enabled }"
                                        v-bind="group.enabled && !settingsLocked ? { onClick: () => toggleConfig(group, toggle) } : {}">
                                        <template v-slot:prepend>
                                            <v-checkbox-btn :model-value="toggle.value" :disabled="!group.enabled || settingsLocked" :aria-label="toggle.label" tabindex="-1" density="compact" color="primary" hide-details @click.stop="toggleConfig(group, toggle)"></v-checkbox-btn>
                                        </template>
                                        <v-list-item-title class="text-body-small knowledge-setting-label">
                                            <span>{{ toggle.label }}</span>
                                            <SceneOverrideResetControl
                                                v-if="toggle.overridden"
                                                :aria-label="`Use global settings for ${group.agentLabel} / ${group.label} / ${toggle.label}`"
                                                :disabled="settingsLocked"
                                                @reset="clearToggle(group, toggle)" />
                                        </v-list-item-title>
                                        <template v-slot:append>
                                            <!-- a switch under a disabled group costs nothing; at Off the slider says so right above it -->
                                            <v-tooltip v-if="toggle.costNote && group.enabled" :text="toggle.costNote" max-width="320" location="start">
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
                            </div>
                        </template>
                    </v-expansion-panel-text>
                </v-expansion-panel>
            </v-expansion-panels>
            <div class="pb-2"></div>
        </v-card>
    </v-menu>
</template>

<script>
import { reactive } from 'vue';
import CharacterKnowledgeModeComparison from './CharacterKnowledgeModeComparison.vue';
import KnowledgeEffortSlider from './KnowledgeEffortSlider.vue';
import KnowledgePendingSave from './KnowledgePendingSave.vue';
import SceneOverrideResetControl from './SceneOverrideResetControl.vue';
import { effortMode, effortPinPatch, queueEffortAcrossSwitch } from '@/utils/knowledgeEffort';
import { resolveKnowledgeToggles, switchTally, thoroughnessSummary } from '@/utils/knowledgeHub';
import {
    effortOverrideState,
    groupClearEntries,
    groupHasOwnedOverride,
    hubClearEntries,
    hubHasOverrides,
    settingClearEntry,
} from '@/utils/knowledgeOverrideOwnership';
import { EFFORT_LABELS } from '@/constants/knowledgeEffort';
import { KNOWLEDGE_RULES } from '@/constants/knowledgeRules';
import {
    PERSPECTIVES_OPEN_HINT,
    canChangePerspectives,
    perspectivesEnabled,
    perspectivesPayload,
} from '@/utils/sceneSettings';

const ENTRY_LIMIT = 5;
const INDIVIDUAL_PANE = 'individual';

// every hub shares one open state for the individual settings, for as long as
// the page lives: a reload starts collapsed again
const individualPane = reactive({ open: false });

export default {
    name: 'CharacterKnowledgeHub',
    components: { CharacterKnowledgeModeComparison, KnowledgeEffortSlider, KnowledgePendingSave, SceneOverrideResetControl },
    props: {
        // absent where the hub is opened for the scene rather than for one
        // character: the popup then carries the scene-wide settings alone
        name: { type: String, default: null },
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
        'applySceneAgentValues',
        'clearSceneAgentValues',
        'sceneOverridesState',
        'queueKnowledgeEffort',
        'openAgentSettings',
    ],
    emits: ['open-knowledge'],
    data() {
        return {
            PERSPECTIVES_OPEN_HINT,
            rules: KNOWLEDGE_RULES,
            open: false,
            loading: false,
            knowledge: null,

        };
    },
    computed: {
        title() {
            return this.name || 'Character knowledge';
        },
        sceneData() {
            return this.scene ? this.scene()?.data : null;
        },
        knowledgeMoment() {
            return JSON.stringify([this.sceneData?.scene_ts, this.sceneData?.characters?.map(character => character.name)]);
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
            const agents = this.getAgents();
            return resolveKnowledgeToggles(agents, { perspectives: this.perspectives }).map((group) => {
                const overlay = agents.find((candidate) => candidate.name === group.agent)?.data?.scene_overrides || {};
                return { ...group, ownedOverridden: groupHasOwnedOverride(overlay, group.agent, group.action) };
            });
        },
        pendingSave() {
            return !!this.sceneOverridesState?.()?.pendingSave;
        },
        saving() {
            return !!this.sceneOverridesState?.()?.busy;
        },
        saveError() {
            return this.sceneOverridesState?.()?.error || null;
        },
        settingsLocked() {
            return this.saving;
        },
        effortOrigin() {
            return effortOverrideState(this.getAgents(), this.effortMode);
        },
        effortOriginTooltip() {
            if (!this.effortOrigin.any) return 'All effort settings come from your global agent settings.';
            return this.effortOrigin.complete
                ? 'All effort settings come from this scene.'
                : 'Mix of scene overrides and global settings.';
        },
        hubOverridden() {
            return hubHasOverrides(this.getAgents());
        },
        summary() {
            return thoroughnessSummary(this.groups, this.perspectives);
        },
        tally() {
            return switchTally(this.groups);
        },
        individualOpen() {
            return individualPane.open ? INDIVIDUAL_PANE : undefined;
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

    },
    watch: {
        knowledgeMoment() {
            if (this.open) this.request();
        },
        // the record's shape follows the scene mode
        perspectives() {
            if (this.open) this.request();
        },
    },
    methods: {
        setIndividualOpen(value) {
            individualPane.open = value === INDIVIDUAL_PANE;
        },
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
            this.request();
        },
        request() {
            if (!this.name) return;
            if (!this.knowledge) this.loading = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_knowledge',
                name: this.name,
            }));
        },
        setPerspectives(enabled) {
            if (this.saving) return false;
            const payload = perspectivesPayload(this.sceneData, enabled);
            if (!payload) return false;
            // a hub-origin switch carries the stop into the new mode as a
            // scene override, not as a global write
            queueEffortAcrossSwitch(this.getAgents(), enabled,
                (stop, mode) => this.queueKnowledgeEffort(stop, mode, { scope: 'scene' }));
            this.getWebsocket().send(JSON.stringify(payload));
            return true;
        },
        applyEffort(stop) {
            if (this.settingsLocked) return;
            this.applySceneAgentValues(effortPinPatch(this.getAgents(), this.effortMode, stop), `Character knowledge effort: ${EFFORT_LABELS[stop]}`);
        },
        clearGroup(group) {
            if (this.settingsLocked) return;
            this.clearSceneAgentValues(groupClearEntries(group.agent, group.action));
        },
        clearToggle(group, toggle) {
            if (this.settingsLocked) return;
            this.clearSceneAgentValues([settingClearEntry(group.agent, group.action, toggle.key)]);
        },
        clearHub() {
            if (this.settingsLocked) return;
            this.clearSceneAgentValues(hubClearEntries());
        },
        toggleGroup(group) {
            if (this.settingsLocked) return false;
            this.applySceneAgentValues([{ agent: group.agent, action: group.action, enabled: !group.enabled, config: {} }], `${group.label}: ${group.enabled ? 'Off' : 'On'}`);
            return true;
        },
        toggleConfig(group, toggle) {
            if (!group.enabled || this.settingsLocked) return false;
            this.applySceneAgentValues([{ agent: group.agent, action: group.action, config: { [toggle.key]: !toggle.value } }], `${toggle.label}: ${toggle.value ? 'Off' : 'On'}`);
            return true;
        },
        handleMessage(data) {
            if (data.type === 'system' && data.id === 'scene.loaded') {
                this.knowledge = null;
                this.loading = false;
                return;
            }
            if (data.type === 'knowledge_changed') {
                const mine = (data.data?.changes || []).some((change) => change.character === this.name);
                if (this.open && mine) this.request();
                return;
            }
            if (data.type !== 'world_state_manager') return;
            if (data.action !== 'character_knowledge') return;
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
.knowledge-setting-label {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 8px;
    white-space: normal;
    overflow: visible;
}
.knowledge-setting-label > :deep(.v-btn) {
    max-width: 100%;
    height: auto;
    min-height: 24px;
    white-space: normal;
}
.knowledge-setting-label > :deep(.v-btn .v-btn__content) {
    white-space: normal;
}

/* the switches keep the spacing they have outside the pane, and the row does
   not grow by Vuetify's taller active title when it opens */
.knowledge-hub-individual :deep(.v-expansion-panel-text__wrapper) {
    padding: 0 0 8px 0;
}
.knowledge-hub-individual :deep(.v-expansion-panel--active > .v-expansion-panel-title) {
    min-height: unset;
}
.knowledge-hub-group {
    min-height: 40px;
}
.knowledge-hub-group :deep(.v-checkbox-btn) {
    flex: 0 0 auto;
}
.knowledge-hub-toggle {
    padding-inline-start: 40px;
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
