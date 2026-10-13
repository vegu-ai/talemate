<template>
    <div>
        <v-card variant="text">
            <v-card-text>
                <div class="d-flex align-center mb-2">
                    <v-btn size="small" :disabled="busy" color="primary" variant="text" class="mr-2" prepend-icon="mdi-refresh" @mousedown.prevent @click.stop="refresh">Refresh</v-btn>
                    <v-chip v-if="externalChange" size="small" label color="warning" variant="text" prepend-icon="mdi-alert-circle-outline" class="mr-2">
                        Changed outside this view — saving overwrites
                        <v-tooltip activator="parent" location="bottom" max-width="400">The game state was changed elsewhere while you have unsaved edits here. Refresh to load the latest, or keep editing and save to overwrite.</v-tooltip>
                    </v-chip>
                    <v-spacer></v-spacer>
                </div>

                <v-divider class="mb-2"></v-divider>

                <v-alert v-if="!loaded" color="muted" density="compact" variant="text">No game state loaded.</v-alert>

                <v-row v-else>
                    <v-col cols="12" md="7">
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

                    <v-col cols="12" md="5">
                        <GameStateWatchedPaths
                            :watched-paths="watchedPaths"
                            :control-paths="controlPaths"
                            :path-settings="pathSettings"
                            :variables="gameStateVariables"
                            :available-paths="gameStatePaths"
                            @debug-path-added="onPathAdded"
                            @set-target="onTargetChanged"
                            @set-settings="onSettingsChanged"
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
import { codeEditorExtensions } from '@/utils/codeEditorTheme.js'
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
            outsideJSON: null,
        };
    },
    computed: {
        watchedPaths() {
            return this.scene?.data?.game_state_watch_paths || [];
        },
        controlPaths() {
            return this.scene?.data?.game_state_control_paths || [];
        },
        pathSettings() {
            return this.scene?.data?.game_state_path_settings || {};
        },
        gameStateVariables() {
            return this.scene?.data?.game_state?.variables || {};
        },
        dirty() {
            return this.gameStateJSON !== this.lastLoadedJSON;
        },
        externalChange() {
            return this.dirty && this.outsideJSON !== null;
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
                    this.onSceneVariables(variables);
                }
            },
            deep: true,
            immediate: true,
        },
        dirty(dirty) {
            if (!dirty && this.outsideJSON !== null) {
                this.adopt(this.outsideJSON);
            }
        },
    },
    methods: {
        adopt(json) {
            this.gameStateJSON = json;
            this.lastLoadedJSON = json;
            this.outsideJSON = null;
            this.validationError = null;
        },
        onSceneVariables(variables) {
            // a pending save's own reply replaces the editor
            if (!this.loaded || this.busy) {
                return;
            }
            const json = JSON.stringify(variables, null, 2);
            if (json === this.lastLoadedJSON) {
                this.outsideJSON = null;
            } else if (this.dirty && json !== this.gameStateJSON) {
                this.outsideJSON = json;
            } else {
                this.adopt(json);
            }
        },
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
                if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
                    this.validationError = 'Game state must be a JSON object';
                    return;
                }
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
                if (message.action === 'operation_done' && message.failed_action === 'update_game_state' && this.busy) {
                    this.busy = false;
                    this.validationError = message.error.message;
                } else if (message.action === 'game_state') {
                    this.loaded = true;
                    this.busy = false;
                    this.adopt(JSON.stringify(message.data.variables || {}, null, 2));

                    // Extract paths from game state variables
                    const variables = message.data.variables || {};
                    const paths = extractGameStatePaths(variables, '', { includeContainers: true });
                    this.gameStatePaths = [...new Set(paths)].sort();
                } else if (message.action === 'game_state_updated') {
                    this.busy = false;
                    this.adopt(JSON.stringify(message.data.variables || {}, null, 2));

                    // Extract paths from game state variables
                    const variables = message.data.variables || {};
                    const paths = extractGameStatePaths(variables, '', { includeContainers: true });
                    this.gameStatePaths = [...new Set(paths)].sort();
                }
            }
        },
        onTargetChanged({ path, target, enabled, settings }) {
            const payload = {
                type: 'devtools',
                action: 'set_game_state_path_target',
                path,
                target,
                enabled,
            };
            if (settings !== undefined) payload.settings = settings;
            this.getWebsocket().send(
                JSON.stringify(payload)
            );
        },
        onSettingsChanged({ path, settings }) {
            this.getWebsocket().send(
                JSON.stringify({
                    type: 'devtools',
                    action: 'set_game_state_path_settings',
                    path,
                    settings,
                })
            );
        },
        onPathAdded(path) {
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

        const extensions = codeEditorExtensions(json(), jsonLinter);

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
