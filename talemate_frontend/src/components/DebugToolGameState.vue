<template>
    <div>
        <v-card variant="text">
            <v-card-text style="overflow: visible;">
                <div class="d-flex justify-end mb-2">
                    <v-btn size="small" @click="openGameStateEditor" prepend-icon="mdi-code-block-braces" color="primary" variant="text">Edit Game State</v-btn>
                </div>

                <v-alert v-if="watchedPaths.length === 0" color="muted" density="compact" variant="text">
                    No watched paths. Add paths to watch in the Game State editor.
                </v-alert>

                <div v-else class="d-flex flex-column" style="gap: 10px; overflow: visible;">
                    <GameStateValueInput
                        v-for="path in displayPaths"
                        :key="path"
                        :path="path"
                        :settings="getSettingsForPath(path)"
                        :answer="answers[path] || null"
                        :refusals="refusals"
                        :show-path-subtitle="Boolean(getSettingsForPath(path).label)"
                        :value="getValueAtPath(path)"
                        @update-value="updateValueAtPath(path, $event)"
                    />
                </div>
            </v-card-text>
        </v-card>
    </div>
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
    name: 'DebugToolGameState',
    components: {
        GameStateValueInput,
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'openWorldStateManager',
    ],
    props: {
        scene: {
            type: Object,
            default: () => ({}),
        },
    },
    data() {
        return {
            answers: {},
            refusals: 0,
        };
    },
    computed: {
        watchedPaths() {
            return this.scene?.data?.game_state_watch_paths || [];
        },
        gameStateVariables() {
            return this.scene?.data?.game_state?.variables || {};
        },
        displayPaths() {
            return sortGameStatePathsByOrder(
                this.scene,
                expandGameStatePaths(this.watchedPaths, this.gameStateVariables),
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
        openGameStateEditor() {
            if (this.openWorldStateManager) {
                this.openWorldStateManager('scene', 'gamestate');
            }
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
