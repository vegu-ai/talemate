<template>
    <div class="text-body-small">
        <div>Pending: {{ state.pendingLabel || 'Knowledge settings change' }}. Save the scene to apply it.</div>
        <v-btn size="small" variant="text" :disabled="!!state.savingScene" @click="retrySceneOverrides">Save and apply</v-btn>
        <v-btn size="small" variant="text" :disabled="!!state.savingScene" @click="discardSceneOverrides">Discard change</v-btn>
    </div>
</template>

<script>
export default {
    name: 'KnowledgePendingSave',
    inject: ['sceneOverridesState', 'retrySceneOverrides', 'discardSceneOverrides'],
    computed: {
        state() {
            return this.sceneOverridesState();
        },
    },
};
</script>
