<template>
    <v-sheet v-if="displayPaths.length" class="game-state-controls mb-2" rounded="lg" border>
        <v-tooltip text="Edit these controls in the game state editor" location="top">
            <template v-slot:activator="{ props }">
                <v-btn
                    v-bind="props"
                    icon="mdi-tune-variant"
                    color="primary"
                    size="small"
                    variant="text"
                    aria-label="Edit these controls in the game state editor"
                    @click="openGameStateEditor"
                />
            </template>
        </v-tooltip>
        <GameStateValueInput
            v-for="path in displayPaths"
            :key="path"
            class="game-state-control"
            :path="path"
            :settings="getSettingsForPath(path)"
            :answer="answers[path] || null"
            :refusals="refusals"
            :value="getValueAtPath(path)"
            :disabled="disabled"
            @update-value="updateValueAtPath(path, $event)"
        />
    </v-sheet>
</template>

<script>
import GameStateValueInput from './GameStateValueInput.vue';
import {
    expandGameStatePaths,
    getGameStateValue,
    resolveGameStatePathSettings,
    sortGameStatePathsByOrder,
} from '@/utils/gameStatePaths.js';

export default {
    name: 'GameStateControls',
    components: {
        GameStateValueInput,
    },
    inject: [
        'getWebsocket',
        'openWorldStateManager',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    props: {
        scene: {
            type: Object,
            default: () => ({}),
        },
        disabled: Boolean,
    },
    data() {
        return {
            answers: {},
            refusals: 0,
        };
    },
    computed: {
        controlPaths() {
            return this.scene?.data?.game_state_control_paths || [];
        },
        gameStateVariables() {
            return this.scene?.data?.game_state?.variables || {};
        },
        displayPaths() {
            return sortGameStatePathsByOrder(
                this.scene,
                expandGameStatePaths(this.controlPaths, this.gameStateVariables),
            );
        },
    },
    methods: {
        handleMessage(message) {
            if (message.type !== 'devtools') return;

            if (message.action === 'game_state_variable_updated') {
                const { path, value } = message.data || {};
                // a fresh object per answer, so an unchanged value still notifies
                if (path) this.answers = { ...this.answers, [path]: { value } };
            } else if (message.error) {
                // a refused write echoes no value, so release every held edit
                this.refusals += 1;
            }
        },
        openGameStateEditor() {
            this.openWorldStateManager('scene', 'gamestate');
        },
        getSettingsForPath(path) {
            return resolveGameStatePathSettings(this.scene, path);
        },
        getValueAtPath(path) {
            return getGameStateValue(this.gameStateVariables, path);
        },
        updateValueAtPath(path, newValue) {
            this.getWebsocket().send(JSON.stringify({
                type: 'devtools',
                action: 'set_game_state_variable',
                path,
                value: newValue,
            }));
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
};
</script>

<style scoped>
.game-state-controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 8px;
    background-color: rgb(var(--v-theme-surface));
}

.game-state-control {
    flex: 1 1 180px;
    min-width: 150px;
    max-width: 260px;
}
</style>
