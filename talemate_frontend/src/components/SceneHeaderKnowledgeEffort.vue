<template>
    <div class="scene-header-effort">
        <CharacterKnowledgeHub>
            <template v-slot:activator="{ props }">
                <KnowledgeEffortChip :mode="mode" :agents="agents" :activator-props="props" :notice="notice" />
            </template>
        </CharacterKnowledgeHub>
    </div>
</template>

<script>
import CharacterKnowledgeHub from './CharacterKnowledgeHub.vue';
import KnowledgeEffortChip from './KnowledgeEffortChip.vue';
import { currentEffort } from '@/utils/knowledgeEffort';

export default {
    name: 'SceneHeaderKnowledgeEffort',
    components: { CharacterKnowledgeHub, KnowledgeEffortChip },
    inject: ['getAgents', 'sceneOverridesState'],
    props: {
        mode: { type: String, required: true },
    },
    computed: {
        agents() {
            return this.getAgents();
        },
        overrides() {
            return this.sceneOverridesState();
        },
        notice() {
            const reasons = [];
            if (currentEffort(this.agents, this.mode).stop === null) {
                reasons.push('Waiting for the agents to report.');
            } else if (this.overrides.pendingSave) {
                const change = this.overrides.pendingLabel ? `A scene override change (${this.overrides.pendingLabel})` : 'A scene override change';
                reasons.push(`${change} waits for a scene save. Open this to save and apply it, or to discard it.`);
            } else if (this.overrides.busy) {
                reasons.push('A scene override change is being applied.');
            }
            if (this.overrides.error) reasons.push(this.overrides.error);
            return reasons.join(' ') || null;
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
