<template>
    <!-- node editor and library -->
    <div class="h-full node-editor mt-0">
        <div class="position-fixed node-editor-outer-container" ref="outer_container">
            <div >

                <NodeEditorModuleProperties ref="moduleProperties" :module="graph" @update="updateModuleProperties" />
                <NodeEditorLog ref="log" />

            </div>
            <v-toolbar density="compact" color="mutedbg" class="mt-0">
                <v-toolbar-title><v-icon class="mr-2" color="primary">mdi-chart-timeline-variant-shimmer</v-icon>Nodes
                </v-toolbar-title>
                <span class="text-caption text-muted">
                    <v-icon size="small" class="mr-1">mdi-file</v-icon>
                    {{ editingNodePath }}
                </span>

                <v-spacer></v-spacer>
                
                <v-menu :close-on-content-click="false">
                    <!-- debug menu -->
                    <template v-slot:activator="{ props }">
                        <v-btn v-bind="props" icon>
                            <v-icon color="primary">mdi-bug</v-icon>
                        </v-btn>
                    </template>

                    <v-list density="compact" v-model:selected="debugMenuSelected" select-strategy="leaf" color="secondary">
                        <v-list-subheader>Debug Logging</v-list-subheader>
                        <v-list-item value="logStateSet">
                            SET State
                            <template v-slot:prepend="{ isSelected }">
                                <v-list-item-action start>
                                    <v-checkbox-btn :model-value="isSelected"></v-checkbox-btn>
                                </v-list-item-action>
                            </template>
                        </v-list-item>
                        <v-list-item value="logStateGet">
                            GET State
                            <template v-slot:prepend="{ isSelected }">
                                <v-list-item-action start>
                                    <v-checkbox-btn :model-value="isSelected"></v-checkbox-btn>
                                </v-list-item-action>
                            </template>
                        </v-list-item>
                    </v-list>
                    
                </v-menu>


                <v-btn @click="requestSceneNodesWithConfirm" color="primary" icon>
                    <v-icon>mdi-refresh</v-icon>
                </v-btn>
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
            <div class="h-[720px] w-full overflow-hidden position-relative node-editor-inner-container" v-resize="onResize" ref="container">
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

                <v-dialog v-model="propertyEditor" :max-width="800" :contained="true" :target="$refs.container">
                    <v-card>
                        <v-card-title>{{ propertyEditorTitle || 'Edit Node Property' }}</v-card-title>
                        <v-alert v-if="propertyEditorValidationErrorMessage" type="error" variant="text"  density="compact">{{ propertyEditorValidationErrorMessage }}</v-alert>
                        <v-card-text v-if="propertyEditorType === 'text'" @keydown.enter="() => { submitPropertyEditor(); }">
                            <v-text-field ref="propertyEditorTextInput" v-model="propertyEditorValue" label="Value" outlined></v-text-field>
                        </v-card-text>
                        <v-card-text v-else-if="propertyEditorType === 'json'">
                            <Codemirror
                                v-model="propertyEditorValue"
                                ref="propertyEditorCodeInput"
                                :extensions="extensions"
                                :style="propertyEditorStyle"
                                @keydown.enter="(ev) => { submitPropertyEditor(ev); }"
                            ></Codemirror>
                            <span class="text-caption text-muted">(Ctrl+Enter to submit changes)</span>
                        </v-card-text>
                    </v-card>
                </v-dialog>
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

            <NodeEditorLibrary 
                ref="library" 
                :scene="scene" 
                :appConfig="appConfig" 
                :templates="templates" 
                :generationOptions="generationOptions" 
                :selectedNodePath="selectedNodePath"
                :selectedNodeName="graph ? graph.talemateTitle : null"
                :selectedNodeRegistry="graph ? graph.talemateRegistry : null"
                @load-node="(path) => requestSceneNodesWithConfirm({path})"
            />

        </div>

    </div>



    <v-snackbar v-model="testErrorMessage" color="red-darken-2" location="top" close-on-content-click :timeout="8000" elevation="5">
        <v-icon>mdi-alert-circle</v-icon>
        <span class="ml-2">{{ testErrorMessage }}</span>
    </v-snackbar>
</template>

<script>
import { LGraphCanvas, LiteGraph } from 'litegraph.js';
import { initializeGraphFromJSON, convertGraphToJSON } from '@/utils/litegraphUtils'
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

    props: {
        scene: Object,
        busy: Boolean,
        appConfig: Object,
        templates: Object,
        generationOptions: Object,
        isVisible: Boolean,
    },
    inject: [
        'getWebsocket', 
        'registerMessageHandler', 
        'unregisterMessageHandler',
        'setEnvCreative',
        'setEnvScene',
    ],
    
    data() {
        return {
            propertyEditor: false,
            propertyEditorType: 'text',
            propertyEditorValue: '',
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
        }
    },
    
    watch: {
        isVisible: {
            handler(newVal) {
                if (newVal) {
                    this.requestSceneNodes();
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

        isTalemateModule(path) {
            return !path.startsWith("scenes/") && !path.startsWith("templates/");
        },

        openPropertyEditor(type, value, callback, validator, title) {
            this.propertyEditorType = type;
            this.propertyEditorValue = value;
            this.propertyEditor = true;
            this.propertyEditorCallback = callback;
            this.propertyEditorValidator = validator;
            this.propertyEditorTitle = title;

            // focus on text field
            this.$nextTick(() => {
                if(this.propertyEditorType === 'text') {
                    this.$refs.propertyEditorTextInput.focus();
                }
            });
        },

        submitPropertyEditor(ev) {

            if(ev && !ev.ctrlKey) {
                return;
            }
            if(ev) {
                ev.preventDefault();
                ev.stopPropagation();
            }


            
            // if last char is a line break, remove it
            if(this.propertyEditorValue.endsWith("\n")) {
                this.propertyEditorValue = this.propertyEditorValue.slice(0, -1);
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
            this.testingPath = this.editingNodePath;
            this.testingGraph = convertGraphToJSON(this.graph);
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'test_run',
                graph: this.testingGraph,
            }));
        },

        startTestSceneLoop() {
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
            // window height - 500px
            const height = window.innerHeight - CANVAS_HEIGHT_OFFSET;

            this.resize(this.$refs.container.clientWidth, height);
        },

        resize(width, height) {
            if(!height) {
                height = window.innerHeight - CANVAS_HEIGHT_OFFSET;
            }

            if(!width) {
                width = this.componentSize.x;
            }

            this.componentSize.x = width;
            this.componentSize.y = height;
            if (this.canvas) {
                this.canvas.resize(this.componentSize.x-1, height);
            }

            if(this.$refs.outer_container) {
                this.$refs.outer_container.style.width = width + "px";
            }
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

            if(error) {
                ltNode.constructor.title_color = "#f44336";
                ltNode.constructor.title_text_color = "#fff";
                ltNode.boxcolor = "#ff0000";

            } else if(!nodeState || nodeState.end_time || nodeState.deactivated || !nodeState.start_time) {
                ltNode.constructor.title_color = null;
                ltNode.constructor.title_text_color = null;
                ltNode.boxcolor = null;
            } else {
                ltNode.constructor.title_color = "#2f2b36";
                ltNode.constructor.title_text_color = "#9575cd";
                ltNode.boxcolor = "#9575cd";
            }
            if(ltNode.inputs) {
                for(const ltInput of ltNode.inputs) {
                    const ltLink = this.graph.links[ltInput.link];
                    if(!ltLink) {
                        //console.log("No link for "+(ltNode.title+"."+ltInput.name), ltInput);
                        continue;
                    }

                    if(deactivated || !nodeState || nodeState.input_values[ltInput.name] === UNRESOLVED) {
                        ltLink.color = "#666";
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
        }
    },
    
    mounted() {
        this.onResize();
        this.registerMessageHandler(this.handleMessage);

        const nodeEditor = this;

        LGraphCanvas.prototype.prompt = function(propertyName, value, callback, ev, multiline, validator) {
            console.log({propertyName, value, callback, ev, multiline, validator});
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
@import "litegraph.js/css/litegraph.css";
</style>

<style>
/* Litegraph styles */

.litegraph.litecontextmenu {
    z-index: 100000;
}

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