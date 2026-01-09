<template>
    <div>
        <v-card variant="text">
            <v-card-text>
                <div class="d-flex align-center mb-2">
                    <v-btn size="small" :disabled="busy" color="primary" variant="text" class="mr-2" prepend-icon="mdi-refresh" @click.stop="refresh">Refresh</v-btn>
                    <v-spacer></v-spacer>
                </div>

                <v-divider class="mb-2"></v-divider>

                <v-alert v-if="!loaded" color="muted" density="compact" variant="text">No game state loaded.</v-alert>

                <v-row v-else>
                    <v-col cols="12" md="8">
                        <div class="codemirror-container">
                            <v-alert v-if="validationError" type="error" density="compact" variant="tonal" class="mb-2">
                                {{ validationError }}
                            </v-alert>
                            <Codemirror
                                v-model="gameStateJSON"
                                :extensions="extensions"
                                :style="editorStyle"
                                @blur="validateAndApply"
                            ></Codemirror>
                        </div>
                    </v-col>

                    <v-col cols="12" md="4">
                        <GameStateWatchedPaths
                            v-model:watched-paths="watchedPaths"
                            :available-paths="gameStatePaths"
                            @path-added="onPathAdded"
                            @update:watched-paths="onWatchedPathsChanged"
                        />
                    </v-col>
                </v-row>
            </v-card-text>
        </v-card>
    </div>
</template>

<script>

import { Codemirror } from 'vue-codemirror'
import { json } from '@codemirror/lang-json'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'
import { linter } from '@codemirror/lint'
import { extractGameStatePaths } from '@/utils/gameStatePaths.js'
import GameStateWatchedPaths from './GameStateWatchedPaths.vue'

export default {
    name: 'GameState',
    components: {
        Codemirror,
        GameStateWatchedPaths,
    },
    props: {
        isVisible: Boolean,
        scene: {
            type: Object,
            default: () => ({}),
        },
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'openDebugTools',
    ],
    data() {
        return {
            busy: false,
            loaded: false,
            gameStateJSON: '',
            lastLoadedJSON: '',
            validationError: null,
            gameStatePaths: [],
        };
    },
    computed: {
        watchedPaths: {
            get() {
                return this.scene?.data?.game_state_watch_paths || [];
            },
            set(value) {
                // This setter is for v-model compatibility in GameStateWatchedPaths
                // The actual update happens through onWatchedPathsChanged
            }
        },
    },
    watch: {
        isVisible(visible) {
            if (visible) {
                this.refresh();
            }
        },
        'scene.data.game_state.variables': {
            handler(variables) {
                if (variables) {
                    const paths = extractGameStatePaths(variables, '', { includeContainers: true });
                    this.gameStatePaths = [...new Set(paths)].sort();
                }
            },
            deep: true,
            immediate: true,
        },
    },
    methods: {
        refresh() {
            this.getWebsocket().send(
                JSON.stringify({ type: 'devtools', action: 'get_game_state' })
            );
        },
        validateAndApply() {
            this.validationError = null;

            // Don't send if nothing changed
            if (this.gameStateJSON === this.lastLoadedJSON) {
                return;
            }

            try {
                const parsed = JSON.parse(this.gameStateJSON);
                this.commitChanges(parsed);
            } catch (e) {
                this.validationError = `Invalid JSON: ${e.message}`;
            }
        },
        commitChanges(variables) {
            this.busy = true;
            this.getWebsocket().send(
                JSON.stringify({
                    type: 'devtools',
                    action: 'update_game_state',
                    variables: variables,
                })
            );
        },
        handleMessage(message) {
            if (message.type === 'devtools') {
                if (message.action === 'game_state') {
                    this.loaded = true;
                    this.busy = false;
                    const json = JSON.stringify(message.data.variables || {}, null, 2);
                    this.gameStateJSON = json;
                    this.lastLoadedJSON = json;
                    this.validationError = null;
                    
                    // Extract paths from game state variables
                    const variables = message.data.variables || {};
                    const paths = extractGameStatePaths(variables, '', { includeContainers: true });
                    this.gameStatePaths = [...new Set(paths)].sort();
                } else if (message.action === 'game_state_updated') {
                    this.busy = false;
                    const json = JSON.stringify(message.data.variables || {}, null, 2);
                    this.gameStateJSON = json;
                    this.lastLoadedJSON = json;
                    this.validationError = null;
                    
                    // Extract paths from game state variables
                    const variables = message.data.variables || {};
                    const paths = extractGameStatePaths(variables, '', { includeContainers: true });
                    this.gameStatePaths = [...new Set(paths)].sort();
                }
            }
        },
        onWatchedPathsChanged(newPaths) {
            // Persist the updated watch paths
            this.getWebsocket().send(
                JSON.stringify({
                    type: 'devtools',
                    action: 'set_game_state_watch_paths',
                    paths: newPaths,
                })
            );
        },
        onPathAdded(path) {
            // When a new path is added, open DebugTools and select gamestate tab
            if (this.openDebugTools) {
                this.$nextTick(() => {
                    this.openDebugTools('gamestate');
                });
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        if (this.isVisible) {
            this.refresh();
        }
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
    setup() {
        const jsonLinter = linter(view => {
            const diagnostics = [];
            const text = view.state.doc.toString();

            try {
                JSON.parse(text);
            } catch (e) {
                const match = e.message.match(/position (\d+)/);
                let from = 0;
                let to = 0;

                if (match) {
                    const pos = parseInt(match[1], 10);
                    const line = view.state.doc.lineAt(pos);
                    from = line.from;
                    to = line.to;
                } else {
                    // Try to find line number from error message
                    const lineMatch = e.message.match(/line (\d+)/);
                    if (lineMatch) {
                        const lineNum = parseInt(lineMatch[1], 10);
                        const line = view.state.doc.line(Math.min(lineNum, view.state.doc.lines));
                        from = line.from;
                        to = line.to;
                    } else {
                        // Default to first line if we can't parse the error
                        from = 0;
                        to = view.state.doc.line(1).to;
                    }
                }

                diagnostics.push({
                    from: from,
                    to: to,
                    severity: 'error',
                    message: e.message
                });
            }

            return diagnostics;
        });

        const extensions = [
            json(),
            oneDark,
            EditorView.lineWrapping,
            jsonLinter
        ];

        const editorStyle = {
            height: "calc(100vh - 470px)",
            minHeight: "400px",
        }

        return {
            extensions,
            editorStyle,
        }
    }
};

</script>

<style scoped>
.codemirror-container {
    width: 100%;
}
</style>


