<template>
    <!-- node editor and library -->
    <div class="h-full node-editor mt-0">
        <div class="position-fixed node-editor-outer-container" ref="outer_container">
            <div >
                <NodeEditorLog ref="log" />
            </div>
            <v-toolbar density="compact" color="mutedbg" class="mt-0">
                <v-tooltip text="Open module library">
                    <template v-slot:activator="{ props }">
                        <v-btn icon v-bind="props" @click="libraryDrawer = true">
                            <v-icon color="primary">mdi-file-tree</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>
                <v-tooltip v-if="hasEditableProperties" text="Module properties">
                    <template v-slot:activator="{ props }">
                        <v-btn icon v-bind="props" @click="propertiesDrawer = true">
                            <v-icon color="primary">mdi-card-bulleted-settings</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>
                <v-divider vertical class="mx-1"></v-divider>
                <v-toolbar-title><v-icon class="mr-2" color="highlight6">mdi-chart-timeline-variant-shimmer</v-icon>Nodes
                </v-toolbar-title>
                
                <span class="text-caption" :class="editingNodeIsScene ? 'text-primary' : 'text-muted'">
                    <v-icon size="small" class="mr-1">mdi-file</v-icon>
                    {{ editingNodeDisplayLabel }}
                </span>

                <span v-if="editingLockedModule" class="ml-2">
                    <v-chip size="x-small" color="muted" variant="text" class="mr-1">
                        <v-icon size="x-small" class="mr-1">mdi-lock</v-icon>
                        Locked
                    </v-chip>
                    <v-btn size="x-small" variant="text" class="text-primary" prepend-icon="mdi-content-copy" @click="openCopyModalFromEditor">
                        Copy to editable scene module
                    </v-btn>
                </span>

                <v-spacer></v-spacer>
                
                <v-menu :close-on-content-click="false">
                    <!-- debug menu -->
                    <template v-slot:activator="{ props }">
                        <v-btn v-bind="props" icon>
                            <v-icon color="primary">mdi-bug</v-icon>
                        </v-btn>
                    </template>

                    <v-list density="compact" color="secondary">
                        <v-list-subheader>Debug Logging</v-list-subheader>
                        <v-list-item>
                            SET State
                            <template v-slot:prepend>
                                <v-checkbox-btn 
                                  density="compact"
                                  color="primary"
                                  class="mr-7"
                                  :model-value="debugMenuSelected.includes('logStateSet')" 
                                  @update:model-value="value => toggleDebugOption('logStateSet', value)"
                                ></v-checkbox-btn>
                            </template>
                        </v-list-item>
                        <v-list-item>
                            GET State
                            <template v-slot:prepend>
                                <v-checkbox-btn 
                                  density="compact"
                                  color="primary"
                                  class="mr-7"
                                  :model-value="debugMenuSelected.includes('logStateGet')" 
                                  @update:model-value="value => toggleDebugOption('logStateGet', value)"
                                ></v-checkbox-btn>
                            </template>
                        </v-list-item>
                        <v-list-item>
                            Clear Log on Test
                            <template v-slot:prepend>
                                <v-checkbox-btn 
                                  density="compact"
                                  color="primary"
                                  class="mr-7"
                                  :model-value="debugMenuSelected.includes('clearLogOnTest')" 
                                  @update:model-value="value => toggleDebugOption('clearLogOnTest', value)"
                                ></v-checkbox-btn>
                            </template>
                        </v-list-item>
                        <v-list-subheader>Utilities</v-list-subheader>
                        <v-tooltip text="Register new Command or Director Chat Action modules without having to reload the scene." max-width="400">
                            <template v-slot:activator="{ props }">
                                <v-list-item @click="syncNodeModules" v-bind="props">
                                    Sync Node Modules
                                    <template v-slot:prepend>
                                        <v-icon color="primary">mdi-refresh</v-icon>
                                    </template>
                                </v-list-item>
                            </template>
                        </v-tooltip>
                    </v-list>
                    
                </v-menu>


                <v-tooltip text="Toggle scene view (Shift click to close all sidebars)">
                    <template v-slot:activator="{ props }">
                        <v-btn icon v-bind="props" @click="(e) => $emit('toggle-scene-view', { shiftKey: !!(e && e.shiftKey) })">
                            <v-icon color="primary">{{ sceneViewVisible ? 'mdi-eye-off' : 'mdi-eye' }}</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

                

                


                <span v-if="!testing">
                    <v-tooltip text="Start the scene loop">
                        <template v-slot:activator="{ props }">
                            <v-btn icon v-bind="props" :disabled="busy" @click="startTestSceneLoop" color="primary">
                                <v-icon>mdi-movie-play</v-icon>
                            </v-btn>
                        </template>
                    </v-tooltip>
                    <v-tooltip text="Start this module">
                        <template v-slot:activator="{ props }">
                            <v-btn icon v-bind="props" :disabled="busy" @click="startTest" color="primary">
                                <v-icon>mdi-play</v-icon>
                            </v-btn>
                        </template>
                    </v-tooltip>
                </span>
                <span v-else-if="breakpoint !== null">
                    <v-tooltip text="Go To Breakpoint">
                        <template v-slot:activator="{ props }">
                            <v-btn icon v-bind="props" @click="gotoBreakpoint" color="delete"><v-icon>mdi-debug-step-over</v-icon></v-btn>
                        </template>
                    </v-tooltip>
                    <v-tooltip text="Release breakpoint">
                        <template v-slot:activator="{ props }">
                            <v-btn icon v-bind="props" @click="releaseBreakpoint" color="delete"><v-icon>mdi-play-pause</v-icon></v-btn>
                        </template>
                    </v-tooltip>
                </span>
                <span v-else>
                    <v-btn :disabled="busy" @click="stopTest" color="error">
                        <v-icon>mdi-stop</v-icon>
                    </v-btn>
                </span>

                <v-btn :disabled="locked" @click="updateSceneNodes" prepend-icon="mdi-check-circle-outline" color="highlight3">
                    Save</v-btn>
            </v-toolbar>
            <v-progress-linear v-if="breakpoint !== null" color="delete" height="2" indeterminate></v-progress-linear>
            <div class="w-full overflow-hidden position-relative node-editor-inner-container" v-resize="onResize" ref="container">
                <canvas ref="canvas" width="1024" height="720" class="border border-solid"></canvas>
                <NodeEditorNodeSearch 
                    ref="nodeSearch"
                    :nodes="sceneNodes && sceneNodes.node_definitions ? sceneNodes.node_definitions.nodes : []"
                    :graph="graph"  
                    :canvas="canvas"
                    :target="$refs.canvas ? $refs.canvas : null"
                />

                <ConfirmActionPrompt 
                    ref="confirmLoad" 
                    action-label="Load module"
                    :description="`Are you sure you want to load module: ${editingNodePath}? Any unsaved changes will be lost.`"
                    confirm-text="Load"
                    cancel-text="Cancel"
                    icon="mdi-folder-open"
                    color="secondary"
                    :contained="true"
                    nax-width="400"
                    @confirm="(params) => loadModuleFromPath(params.path)"
                />

                <ConfirmActionPrompt 
                    ref="confirmDiscardPropertyEditor" 
                    action-label="Discard changes"
                    description="You have unsaved changes in the property editor. Discard them?"
                    confirm-text="Discard"
                    cancel-text="Keep editing"
                    icon="mdi-alert-outline"
                    color="delete"
                    :contained="true"
                    :max-width="400"
                    @confirm="confirmDiscardPropertyEditor"
                />

                <v-dialog v-model="propertyEditor" :max-width="800" :contained="true" :target="$refs.container" @update:model-value="onPropertyEditorModelUpdate">
                    <v-card>
                        <v-card-title>{{ propertyEditorTitle || 'Edit Node Property' }}</v-card-title>
                        <v-alert v-if="propertyEditorValidationErrorMessage" type="error" variant="text"  density="compact">{{ propertyEditorValidationErrorMessage }}</v-alert>
                        <v-card-text v-if="propertyEditorType === 'text'">
                            <v-text-field ref="propertyEditorTextInput" v-model="propertyEditorValue" label="Value" outlined
                            @keydown.enter="() => { submitPropertyEditor(); }"></v-text-field>
                        </v-card-text>
                        <v-card-text v-else-if="propertyEditorType === 'color'">
                            <v-color-picker
                                v-model="propertyEditorValue"
                                mode="hex"
                                :modes="['hex']"
                                width="100%"
                            />
                            <v-text-field
                                class="mt-3"
                                v-model="propertyEditorValue"
                                label="Color (#RRGGBB)"
                                outlined
                                @keydown.enter="() => { submitPropertyEditor(); }"
                            />
                        </v-card-text>
                        <v-card-text v-else-if="propertyEditorType === 'json'">
                            <Codemirror
                                v-model="propertyEditorValue"
                                ref="propertyEditorCodeInput"
                                :extensions="extensions"
                                :style="propertyEditorStyle"
                                @keydown.capture="onPropertyEditorKeydown"
                            ></Codemirror>
                            <span class="text-caption text-muted">(Ctrl+Enter to submit changes)</span>
                        </v-card-text>
                        <v-card-actions v-if="propertyEditorType === 'color'">
                            <v-spacer></v-spacer>
                            <v-btn variant="text" @click="cancelPropertyEditor">Cancel</v-btn>
                            <v-btn color="primary" @click="submitPropertyEditor()">Apply</v-btn>
                        </v-card-actions>
                    </v-card>
                </v-dialog>

                <ConfirmActionPrompt 
                    ref="confirmExitCreative" 
                    action-label="Exit node editor"
                    :description="exitConfirmDescription"
                    confirm-text="Exit"
                    cancel-text="Cancel"
                    icon="mdi-exit-to-app"
                    color="delete"
                    :contained="true"
                    :max-width="400"
                    @confirm="exitCreativeMode"
                />
            </div>

            <v-sheet v-if="editingLockedModule" class="transparent-background">
                <p v-if="scene.env === 'creative'" class="ma-2 text-muted text-caption">
                    <v-icon size="small" class="mr-1">mdi-lock</v-icon>
                    The node editor is locked in this environment. Switch to <v-btn size="x-small" variant="text" @click="setEnvCreative" class="text-primary" prepend-icon="mdi-palette">creative mode</v-btn> to edit nodes.
                </p>
                <p class="ma-2 text-muted text-caption">
                    <v-icon size="small" class="mr-1">mdi-lock</v-icon>
                    This module is locked and cannot be directly edited.
                    <span v-if="editingOriginalSceneLoop">
                        <v-btn size="x-small" variant="text" @click="initiateCustomSceneLoop" class="text-primary" prepend-icon="mdi-plus">Create custom main loop for {{ scene.name }}</v-btn>
                    </span>
                    <span v-else>
                        <v-btn size="x-small" variant="text" @click="copyToSceneModule" class="text-primary" prepend-icon="mdi-content-copy">Copy as editable module for {{ scene.name }}</v-btn>
                    </span>
                </p>
            </v-sheet>

            <v-navigation-drawer
                v-model="libraryDrawer"
                location="left"
                temporary
                width="500"
            >
                <NodeEditorLibrary
                    ref="library"
                    :scene="scene"
                    :appConfig="appConfig"
                    :templates="templates"
                    :generationOptions="generationOptions"
                    :selectedNodePath="selectedNodePath"
                    :selectedNodeName="graph ? graph.talemateTitle : null"
                    :selectedNodeRegistry="graph ? graph.talemateRegistry : null"
                    :sceneReadyForNodeEditing="sceneReadyForNodeEditing"
                    :nodeDefinitions="sceneNodes?.node_definitions?.nodes || {}"
                    @load-node="(path) => { libraryDrawer = false; requestSceneNodesWithConfirm({path}); }"
                />
            </v-navigation-drawer>

            <v-navigation-drawer
                v-model="propertiesDrawer"
                location="left"
                temporary
                width="600"
            >
                <NodeEditorModuleProperties
                    ref="moduleProperties"
                    :module="graph"
                    @update="updateModuleProperties"
                />
            </v-navigation-drawer>

        </div>

    </div>



    <v-snackbar v-model="testErrorMessage" color="red-darken-2" location="top" close-on-content-click :timeout="8000" elevation="5">
        <v-icon>mdi-alert-circle</v-icon>
        <span class="ml-2">{{ testErrorMessage }}</span>
    </v-snackbar>
</template>

<script>
import { LGraphCanvas, LiteGraph } from 'litegraph.js';
import { initializeGraphFromJSON, normalizeHexColor } from '@/utils/litegraphUtils'
import { convertGraphToJSON, convertSelectedGraphToJSON } from '@/utils/exportGraph.js'
//import '@/utils/litegraphSearchBox'
import { Codemirror } from 'vue-codemirror'
import { markdown } from '@codemirror/lang-markdown'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'

import NodeEditorLibrary from './NodeEditorLibrary.vue';
import NodeEditorLog from './NodeEditorLog.vue';
import NodeEditorNodeSearch from './NodeEditorNodeSearch.vue';
import NodeEditorModuleProperties from './NodeEditorModuleProperties.vue';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';

const UNRESOLVED = "type(<class 'talemate.game.engine.nodes.core.UNRESOLVED'>)";
const NONE = "NoneType(None)";
const CANVAS_HEIGHT_OFFSET = 500;

export default {
    name: 'NodeEditor',

    components: {
        Codemirror,
        NodeEditorLibrary,
        NodeEditorLog,
        NodeEditorModuleProperties,
        ConfirmActionPrompt,
        NodeEditorNodeSearch,
    },

    emits: ['toggle-scene-view'],

    props: {
        scene: Object,
        busy: Boolean,
        appConfig: Object,
        templates: Object,
        generationOptions: Object,
        isVisible: Boolean,
        sceneViewVisible: Boolean,
    },
    inject: [
        'getWebsocket', 
        'registerMessageHandler', 
        'unregisterMessageHandler',
        'setEnvCreative',
        'setEnvScene',
    ],

    provide() {
        return {
            getSelectedNodes: this.getSelectedNodes,
        }
    },
    
    data() {
        return {
            propertyEditor: false,
            propertyEditorType: 'text',
            propertyEditorValue: '',
            propertyEditorOriginalValue: '',
            propertyEditorForceClose: false,
            propertyEditorCallback: () => {},
            propertyEditorValidator: (v) => v,
            propertyEditorValidationErrorMessage: null,
            propertyEditorTitle: null,
            nodeLibrarySearch: '',
            selectedNodePath: null,
            debugLoadPath: "select-actor-for-turn.json",
            sceneNodes: {},
            graph: null,
            canvas: null,
            testing: false,
            testingPath: null,
            testingGraph: null,
            nodeState: {},
            testErrorMessage: null,
            breakpoint: null,
            centerOnNode: null,
            debugMenuSelected: [],
                libraryDrawer: true,
                propertiesDrawer: false,
            exitConfirmDescription: "You have unsaved changes in the node editor. Exit node editor and discard them?",
            componentSize: {
                x: 0,
                y: 0,
            },

            nodeStateHandlers: {
                "core/Watch": (ltNode, nodeState) => {
                    let value = nodeState.input_values.value;

                    if(value === UNRESOLVED || value === NONE) {
                        return;
                    }

                    this.$refs.log.addEntry(ltNode, value, nodeState);
                },
                "core/functions/Breakpoint": (ltNode, nodeState) => {
                    let value = nodeState.input_values.state;

                    if(value === UNRESOLVED || value === NONE) {
                        return;
                    }

                    this.$refs.log.addEntry(ltNode, value, nodeState);
                },
                "state/SetState": (ltNode, nodeState) => {
                    if(this.logStateSet) {
                        let value = nodeState.input_values.value;
                        this.$refs.log.addEntry(ltNode, value, nodeState);
                    }
                },
                "state/GetState": (ltNode, nodeState) => {
                    if(this.logStateGet) {
                        let value = nodeState.output_values.value;
                        this.$refs.log.addEntry(ltNode, value, nodeState);
                    }
                }
            }
        }
    },

    computed: {
        editingNodePath() {
            if(!this.selectedNodePath) {
                return this.scene.data.nodes_filename;
            }
            return this.selectedNodePath;
        },
        editingNodeIsScene() {
            if(!this.editingNodePath) {
                return false;
            }
            const normalized = this.editingNodePath.replace(/\\/g, '/');
            return normalized.startsWith('scenes/');
        },
        editingNodeIsAgent() {
            if(!this.editingNodePath) {
                return false;
            }
            const normalized = this.editingNodePath.replace(/\\/g, '/');
            return normalized.startsWith('src/talemate/agents/');
        },
        editingNodeAgentName() {
            if(!this.editingNodeIsAgent) {
                return null;
            }
            const normalized = this.editingNodePath.replace(/\\/g, '/');
            const parts = normalized.split('/');
            return parts[3] || null;
        },
        editingNodeDisplayName() {
            const path = this.editingNodePath || '';
            const base = (path.split('/').pop() || path).replace(/\.json$/, '');
            return base.replace(/-/g, ' ');
        },
        editingNodeDisplayLabel() {
            if (this.editingNodeIsAgent && this.editingNodeAgentName) {
                return `${this.editingNodeAgentName} · ${this.editingNodeDisplayName}`;
            }
            return this.editingNodeDisplayName;
        },
        editingLockedModule() {
            return this.isTalemateModule(this.editingNodePath);
        },
        editingOriginalSceneLoop() {
            const editingNodeFilename = this.editingNodePath.split('/').pop();
            return this.graph && this.graph.talemateRegistry === 'scene/SceneLoop' && this.scene.data.nodes_filename === editingNodeFilename;
        },
        locked() {
            return this.editingLockedModule;
        },
        logStateSet() {
            return this.debugMenuSelected.includes('logStateSet');
        },
        logStateGet() {
            return this.debugMenuSelected.includes('logStateGet');
        },
        clearLogOnTest() {
            return this.debugMenuSelected.includes('clearLogOnTest');
        },
        hasEditableProperties() {
            if (!this.graph || !this.graph.talemateFields) {
                return false;
            }
            const editableTypes = ['str', 'int', 'float', 'bool', 'text'];
            for (let key in this.graph.talemateFields) {
                if (editableTypes.includes(this.graph.talemateFields[key].type)) {
                    return true;
                }
            }
            return false;
        },
        sceneReadyForNodeEditing() {
            if(!this.scene) {
                return false;
            }
            return this.scene.data.save_files && this.scene.data.save_files.length > 0;
        }
    },
    
    watch: {
        isVisible: {
            handler(newVal) {
                if (newVal) {
                    // reload only if nothing is currently loaded
                    if(!this.graph) {
                        console.log("Loading node module");
                        this.requestSceneNodes();
                    } else {
                        // Just resize and refresh the canvas when becoming visible again
                        this.$nextTick(() => {
                            setTimeout(() => {
                                this.onResize();
                                if (this.canvas) {
                                    this.canvas.setDirty(true, true);
                                }
                            }, 150);
                        });
                    }
                }
            },
            immediate: true
        },
        
        sceneNodes: {
            handler(newNodes) {
                if (Object.keys(newNodes).length > 0) {
                    this.loadGraph();
                }
            },
            deep: true
        },
    },
    
    methods: {
        openCopyModalFromEditor() {
            this.libraryDrawer = true;
            this.$nextTick(() => {
                setTimeout(() => {
                    if (this.$refs.library && this.$refs.library.copyModuleToScene) {
                        this.$refs.library.copyModuleToScene(null);
                    }
                }, 50);
            });
        },
        requestExitCreative() {
            // If there are unsaved changes, ask for confirmation
            if (this.graph && this.graph.hasChanges && this.graph.hasChanges()) {
                if (this.$refs.confirmExitCreative) {
                    this.$refs.confirmExitCreative.initiateAction({});
                    return;
                }
            }
            this.exitCreativeMode();
        },

        exitCreativeMode() {
            this.setEnvScene();
        },

        isTalemateModule(path) {
            // Normalize path separators to forward slashes for consistent processing
            const normalizedPath = path.replace(/\\/g, '/');
            return !normalizedPath.startsWith("scenes/") && !normalizedPath.startsWith("templates/");
        },

        openPropertyEditor(type, value, callback, validator, title) {
            this.propertyEditorType = type;
            this.propertyEditorValue = value;
            this.propertyEditorOriginalValue = value;
            this.propertyEditorForceClose = false;
            this.propertyEditor = true;
            this.propertyEditorCallback = callback;
            this.propertyEditorValidator = validator;
            this.propertyEditorTitle = title;
            this.propertyEditorValidationErrorMessage = null;

            // focus on text field
            this.$nextTick(() => {
                if(this.propertyEditorType === 'text') {
                    setTimeout(() => {
                        this.$refs.propertyEditorTextInput.focus();
                    }, 100);
                }
            });
        },

        cancelPropertyEditor() {
            this.propertyEditorForceClose = true;
            this.propertyEditorValue = this.propertyEditorOriginalValue;
            this.propertyEditor = false;
        },

        submitPropertyEditor(ev) {

            if(ev && !(ev.ctrlKey || ev.metaKey)) {
                return;
            }
            if(ev) {
                ev.preventDefault();
                ev.stopPropagation();
            }
            
            // if last char is a line break, remove it
            if(this.propertyEditorValue && this.propertyEditorValue.endsWith("\n")) {
                this.propertyEditorValue = this.propertyEditorValue.slice(0, -1);
            } else if(!this.propertyEditorValue) {
                this.propertyEditorValue = "";
            }

            if(this.propertyEditorValidator) {
                try {
                    this.propertyEditorValue = this.propertyEditorValidator(this.propertyEditorValue);
                } catch (e) {
                    this.propertyEditorValidationErrorMessage = e.message;
                    return;
                }
            }


            this.propertyEditorCallback(this.propertyEditorValue);
            this.propertyEditorForceClose = true;
            this.propertyEditor = false;
        },

        onPropertyEditorKeydown(ev) {
            if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') {
                ev.preventDefault();
                ev.stopPropagation();
                this.submitPropertyEditor(ev);
            }
        },

        onPropertyEditorModelUpdate(newValue) {
            // Intercept close attempts to confirm discarding unsaved changes
            if (newValue === false) {
                if (this.propertyEditorForceClose) {
                    this.propertyEditorForceClose = false;
                    this.propertyEditor = false;
                    return;
                }

                const hasUnsavedChanges = this.propertyEditorValue !== this.propertyEditorOriginalValue;
                if (hasUnsavedChanges) {
                    // Reopen the dialog and prompt for confirmation
                    this.$nextTick(() => {
                        this.propertyEditor = true;
                        if (this.$refs.confirmDiscardPropertyEditor) {
                            this.$refs.confirmDiscardPropertyEditor.initiateAction({});
                        }
                    });
                } else {
                    this.propertyEditor = false;
                }
            } else {
                this.propertyEditor = true;
            }
        },

        confirmDiscardPropertyEditor() {
            this.propertyEditorForceClose = true;
            this.propertyEditor = false;
        },

        updateModuleProperties(properties) {
            this.graph.talemateProperties = properties;
        },

        debugLoadGraph() {
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'request_node_module',
                path: this.debugLoadPath,
            }));
        },
        loadGraph() {
            // Clear existing graph if any
            if (this.graph) {
                this.graph.clear();
            }
            
            // Initialize new graph from scene nodes
            this.graph = initializeGraphFromJSON(this.sceneNodes, this.centerOnNode);
            this.centerOnNode = null;
            console.log("Loaded graph", this.graph, this.sceneNodes);

            // If canvas exists, update it with new graph
            if (this.canvas) {
                this.canvas.setGraph(this.graph);
            } else {
                // Initialize canvas with new graph
                this.canvas = new LGraphCanvas(this.$refs.canvas, this.graph);
                this.canvas.showShowNodePanel = function(){};
                this.canvas.align_to_grid = true;
                this.canvas.container = this.$refs.outer_container;
            }

            this.canvas.read_only = this.editingLockedModule;

            setTimeout(() => {
                this.graph.setFingerprint();
            }, 1500);

            // Start graph execution
            //this.graph.start();

            this.$nextTick(() => {
                this.onResize();
                this.applyNodeState();
            });
        },

        getSelectedNodes() {
            return convertSelectedGraphToJSON(this.graph, this.canvas.selected_nodes);
        },

        initiateCustomSceneLoop() {
            if(this.editingOriginalSceneLoop) {
                this.$refs.library.startNewModule('copy', "Scene Loop", 'scene/SceneLoop');
            } else {
                this.$refs.library.startNewModule('scene/SceneLoop');
            }
        },

        copyToSceneModule() {
            this.$refs.library.startNewModule('copy', this.graph.talemateTitle, this.graph.talemateRegistry);
        },

        requestSceneNodesWithConfirm(params) {
            if(this.graph && this.graph.hasChanges()) {
                this.$refs.confirmLoad.initiateAction(params);
            } else {
                if(!params || !params.path) {
                    this.selectedNodePath = null;
                    this.requestSceneNodes();
                } else {
                    this.loadModuleFromPath(params.path);
                }
            }
        },

        requestSceneNodes() {
            console.log("Requesting node module", this.editingNodePath);
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'request_node_module',
                path: this.editingNodePath,
            }));
        },

        updateSceneNodes() {
            const graph_data = convertGraphToJSON(this.graph);

            console.log({graph_data});

            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'update_node_module',
                graph: graph_data,
                path: this.editingNodePath,
            }));

            this.graph.setFingerprint();

        },

        loadModuleFromPath(path) {
            this.selectedNodePath = path;
            this.$nextTick(() => {
                this.requestSceneNodes();
            });
        },

        restartTest() {

            if(!this.testingGraph) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'test_restart',
                graph: this.testingGraph,
            }));
        },

        startTest() {
            if (this.clearLogOnTest) {
                this.$refs.log.clearLog();
            }
            this.testingPath = this.editingNodePath;
            this.testingGraph = convertGraphToJSON(this.graph);
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'test_run',
                graph: this.testingGraph,
            }));
        },

        startTestSceneLoop() {
            if (this.clearLogOnTest) {
                this.$refs.log.clearLog();
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'test_run_scene_loop',
            }));
        },

        stopTest() {
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'test_stop',
            }));
        },

        onResize() {
            // Compute available height based on container's top offset
            if (!this.$refs.container) {
                return;
            }
            const rect = this.$refs.container.getBoundingClientRect();
            const available = window.innerHeight - rect.top - 8; // small bottom padding
            const height = Math.max(300, available);
            this.resize(this.$refs.container.clientWidth, height);
        },

        resize(width, height) {
            if(!height) {
                const rect = this.$refs.container ? this.$refs.container.getBoundingClientRect() : { top: 0 };
                height = Math.max(300, window.innerHeight - rect.top - 8);
            }

            if(!width) {
                width = this.componentSize.x;
            }

            this.componentSize.x = width;
            this.componentSize.y = height;
            if (this.$refs.container) {
                this.$refs.container.style.height = height + 'px';
            }
            if (this.canvas) {
                this.canvas.resize(this.componentSize.x-1, height);
            }

            if(this.$refs.outer_container) {
                this.$refs.outer_container.style.width = width + "px";
            }
        },

        indicatedDeactivatedSocket(nodeDeactivated, input, value) {
            if(nodeDeactivated && !input.optional && value === "<class 'talem...e.UNRESOLVED'>") {
                input.color_off = "#f44336";
                input.color_on = "#f44336";
            } else {
                input.color_off = null;
                input.color_on = null;
            }
        },

        applyHighlightStyleToLitegraphNode(ltNode, nodeState) {
            // IMPORTANT: never mutate ltNode.constructor.* for styling here.
            // LiteGraph node "constructors" are shared across all instances of the same node type,
            // which causes *every* node of that type to appear active/errored.
            //
            // Instead, apply styling per-instance and keep a base-style snapshot to restore later.
            const error = (nodeState && nodeState.error);
            const highlightState = error
                ? "error"
                : (!nodeState || nodeState.end_time || nodeState.deactivated || !nodeState.start_time)
                    ? null
                    : "active";

            if (!ltNode._talemateBaseStyle) {
                ltNode._talemateBaseStyle = {
                    color: ltNode.color,
                    title_text_color: ltNode.title_text_color,
                    boxcolor: ltNode.boxcolor,
                };
                ltNode._talemateHighlightState = null;
            }

            if (!highlightState) {
                // If we were highlighting, restore the base style.
                if (ltNode._talemateHighlightState) {
                    const base = ltNode._talemateBaseStyle || {};
                    if (base.hasOwnProperty("color")) ltNode.color = base.color;
                    if (base.hasOwnProperty("title_text_color")) ltNode.title_text_color = base.title_text_color;
                    if (base.hasOwnProperty("boxcolor")) ltNode.boxcolor = base.boxcolor;
                }

                // Update base style while idle so it tracks edits/changes.
                ltNode._talemateBaseStyle = {
                    color: ltNode.color,
                    title_text_color: ltNode.title_text_color,
                    boxcolor: ltNode.boxcolor,
                };
                ltNode._talemateHighlightState = null;
                return;
            }

            // Transition from idle -> highlighted: snapshot base style.
            if (!ltNode._talemateHighlightState) {
                ltNode._talemateBaseStyle = {
                    color: ltNode.color,
                    title_text_color: ltNode.title_text_color,
                    boxcolor: ltNode.boxcolor,
                };
            }

            if (highlightState === "error") {
                ltNode.color = "#f44336";
                ltNode.title_text_color = "#fff";
                ltNode.boxcolor = "#ff0000";
            } else {
                ltNode.color = "#2f2b36";
                ltNode.title_text_color = "#9575cd";
                ltNode.boxcolor = "#9575cd";
            }

            ltNode._talemateHighlightState = highlightState;
        },

        applyNodeState(nodeState) {
            
            
            if(!this.graph || !nodeState) {
                return;
            }

            this.nodeState[nodeState.node_id] = nodeState;

            //console.log("Applying node state", nodeState);

            const ltNode = this.graph._nodes.find(node => node.talemateId === nodeState.node_id);
            let error = (nodeState && nodeState.error);

            if(error) {
                this.$refs.log.addEntry(ltNode || {
                    talemateId: nodeState.node_id,
                    title: "Module",
                }, nodeState.error, nodeState);
            }

            if(!ltNode) {
                return;
            }

            //console.log({ltNode, title:ltNode.title, nodeState: nodeState});

            ltNode.talemateState = nodeState;

            if(nodeState && nodeState.end_time) {
                if(ltNode.onNodeStateChanged) {
                    ltNode.onNodeStateChanged(nodeState);
                }

                if(this.nodeStateHandlers[ltNode.type]) {
                    this.nodeStateHandlers[ltNode.type](ltNode, nodeState);
                }

            }

            let deactivated = (nodeState && nodeState.deactivated);

            this.applyHighlightStyleToLitegraphNode(ltNode, nodeState);
            if(ltNode.inputs) {
                for(const ltInput of ltNode.inputs) {
                    this.indicatedDeactivatedSocket(deactivated, ltInput, nodeState.input_values[ltInput.name]);
                    const ltLink = this.graph.links[ltInput.link];
                    if(!ltLink) {
                        //console.log("No link for "+(ltNode.title+"."+ltInput.name), ltInput);
                        continue;
                    }

                    const inputUnresolved = nodeState.input_values[ltInput.name] === "<class 'talem...e.UNRESOLVED'>";

                    if(deactivated || !nodeState || inputUnresolved) {
                        if(deactivated && !ltInput.optional && inputUnresolved) {
                            ltLink.color = "#f44336";
                        } else {
                            ltLink.color = "#666";
                        }
                    } else {
                        ltLink.color = "#9575cd";
                    }

                    //console.log({ltInput, ltLink});
                }
            }

            this.canvas.setDirty(true, true);
        },

        reapplyCurrentNodeState() {
            for(const nodeId in this.nodeState) {
                this.applyNodeState(this.nodeState[nodeId]);
            }
        },

        setBreakpoint(breakpoint) {
            this.breakpoint = breakpoint;
        },

        gotoBreakpoint() {
            if(!this.breakpoint) {
                return;
            }
            // load graph based on module path
            this.centerOnNode = this.breakpoint.node.id;
            this.loadModuleFromPath(this.breakpoint.module_path);
        },

        releaseBreakpoint() {
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'release_breakpoint',
            }));
        },

        restartSceneLoop() {
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'restart_scene_loop',
            }));
        },

        syncNodeModules() {
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'sync_node_modules',
            }));
        },

        handleMessage(message) {
            if(message.type !== 'node_editor') {
                return;
            }

            if(message.action === 'node_module') {
                this.sceneNodes = message.data;
                this.selectedNodePath = message.data.path_info.relative_path;
            } else if(message.action === 'test_started') {
                this.testing = true;
            } else if(message.action === 'test_stopped') {
                this.testing = false;
                this.testingPath = null;
                this.testingGraph = null;
            } else if(message.action === 'test_error') {
                this.testing = false;
                this.testingPath = null;
                this.testingGraph = null;
                this.testErrorMessage = message.data.error;
            } else if(message.action === 'node_state') {
                //this.nodeState = message.data.stack;
                console.log("Received node state", {incoming: message.data.stack, current: this.nodeState});

                this.reapplyCurrentNodeState();

                if(message.data.stack.length > 0) {
                    for (let idx = 0; idx < message.data.stack.length; idx++) {

                        this.applyNodeState(message.data.stack[idx]);
                    }
                }
            } else if(message.action === 'breakpoint') {
                console.log("Received breakpoint", message.data);
                this.setBreakpoint(message.data);
            } else if(message.action === 'breakpoint_released') {
                console.log("Breakpoint released");
                this.breakpoint = null;
            }
        },

        toggleDebugOption(option, value) {
            if (value) {
                this.debugMenuSelected.push(option);
            } else {
                this.debugMenuSelected = this.debugMenuSelected.filter(o => o !== option);
            }
            // Save to local storage
            localStorage.setItem('talemate_debug_options', JSON.stringify(this.debugMenuSelected));
        }
    },
    
    mounted() {
        this.onResize();
        this.registerMessageHandler(this.handleMessage);

        // Load debug menu state from local storage if available
        const savedDebugOptions = localStorage.getItem('talemate_debug_options');
        if (savedDebugOptions) {
            try {
                this.debugMenuSelected = JSON.parse(savedDebugOptions);
            } catch (e) {
                console.error("Failed to parse saved debug options", e);
            }
        }

        const nodeEditor = this;

        // LiteGraph calls prompt(title, value, callback, event, multiline).
        // We extend it with optional params (validator, options) from our custom widgets.
        LGraphCanvas.prototype.prompt = function(title, value, callback, ev, multiline, validator, options) {
            if (options && options.editorType === 'color') {
                const dialogTitle = options.title || 'Edit color';
                nodeEditor.openPropertyEditor(
                    'color',
                    value || '',
                    (newValue) => {
                        callback(newValue);
                        this.setDirty(true);
                    },
                    normalizeHexColor,
                    dialogTitle
                );
                return;
            }

            nodeEditor.openPropertyEditor(multiline ? 'json' : 'text', value, (newValue) => {
                callback(newValue);
                this.setDirty(true);
            }, validator);
        }

        LGraphCanvas.onShowPropertyEditor = function(item, options, event, menu, node) {
            const property = item.property || "title";
            const value = node[property];
            const title = "Edit " + property;
            nodeEditor.openPropertyEditor('text', value, (newValue) => {
                node[property] = newValue;
                node.setDirtyCanvas(true, true);
            }, null, title);
        }

        LGraphCanvas.prototype.showSearchBox = function(event, options) {
            console.log("Showing search box", event, options);
            nodeEditor.$refs.nodeSearch.open(event);
            return {
                focus: () => {}
            }
        }
    },
    
    beforeUnmount() {
        if (this.graph) {
            this.graph.clear();
            LiteGraph.closeAllContextMenus(window);
        }
        if(this.testing) {
            this.stopTest();
        }
        this.unregisterMessageHandler(this.handleMessage);
    },

    setup() {

        const extensions = [
            markdown(),
            oneDark,
            EditorView.lineWrapping
        ];

        const propertyEditorStyle = {
            maxHeight: "600px"
        }

        return {
            extensions,
            propertyEditorStyle,
        }
    }
}
</script>

<style scoped>
</style>

<style>
/* Litegraph styles */
@import "litegraph.js/css/litegraph.css";


.litegraph.lite-search-item {
    padding: 2px;
    font-size: 12px;
    color: rgb(var(--v-theme-muted));
}

.litegraph.lite-search-item:hover {
    color: rgb(var(--v-theme-primary));
    background-color: #000;
}

.litegraph.litesearchbox input {
    border: 1px solid rgb(var(--v-theme-primary));
}

/* node editor styles */

.transparent-background {
    background-color: transparent;
}

.breakpoint-indicator {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    z-index: 1000;
}
</style>