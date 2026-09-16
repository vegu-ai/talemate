<template>
    <div class="scene-header-effort">
        <KnowledgeEffortSlider
            compact
            :mode="mode"
            :agents="agents"
            :pin="true"
            :disabled="!!disabledReason"
            :notice="notice"
            @apply="applyEffort" />
        <v-menu v-if="overrides.pendingSave" v-model="pendingOpen" location="bottom end">
            <template v-slot:activator="{ props: menuProps }">
                <v-tooltip text="Save or discard the pending knowledge settings change" location="bottom" :disabled="pendingOpen">
                    <template v-slot:activator="{ props: tooltipProps }">
                        <v-btn
                            v-bind="mergeProps(menuProps, tooltipProps)"
                            class="scene-header-effort__pending"
                            icon="mdi-content-save-alert-outline"
                            size="x-small"
                            variant="text"
                            color="warning"
                            aria-label="Save or discard the pending knowledge settings change" />
                    </template>
                </v-tooltip>
            </template>
            <v-card class="pa-3" max-width="320">
                <KnowledgePendingSave />
            </v-card>
        </v-menu>
    </div>
</template>

<script>
import { mergeProps } from 'vue';
import KnowledgeEffortSlider from './KnowledgeEffortSlider.vue';
import KnowledgePendingSave from './KnowledgePendingSave.vue';
import { EFFORT_LABELS } from '@/constants/knowledgeEffort';
import { currentEffort, effortPinPatch } from '@/utils/knowledgeEffort';

export default {
    name: 'SceneHeaderKnowledgeEffort',
    components: { KnowledgeEffortSlider, KnowledgePendingSave },
    inject: ['getAgents', 'applySceneAgentValues', 'sceneOverridesState'],
    props: {
        mode: { type: String, required: true },
    },
    data() {
        return {
            pendingOpen: false,
        };
    },
    computed: {
        agents() {
            return this.getAgents();
        },
        overrides() {
            return this.sceneOverridesState();
        },
        settingsLocked() {
            return !!this.overrides.busy;
        },
        disabledReason() {
            if (currentEffort(this.agents, this.mode).stop === null) {
                return 'Waiting for the agents to report.';
            }
            if (this.overrides.pendingSave) {
                return 'A knowledge settings change waits for a scene save. Use the save button next to this control to save and apply it, or to discard it.';
            }
            if (this.settingsLocked) {
                return 'A knowledge settings change is being applied.';
            }
            return null;
        },
        notice() {
            return [this.disabledReason, this.overrides.error].filter(Boolean).join(' ') || null;
        },
    },
    watch: {
        // the open menu unmounts with the pending change; a stale true would reopen it on the next one
        'overrides.pendingSave'(pending) {
            if (!pending) this.pendingOpen = false;
        },
    },
    methods: {
        mergeProps,
        applyEffort(stop) {
            if (this.settingsLocked) return;
            this.applySceneAgentValues(effortPinPatch(this.agents, this.mode, stop), `Character knowledge effort: ${EFFORT_LABELS[stop]}`);
        },
    },
};
</script>

<style scoped>
.scene-header-effort {
    display: inline-flex;
    align-items: center;
    gap: 4px;
}
</style>
