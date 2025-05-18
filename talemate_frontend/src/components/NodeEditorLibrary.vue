<template>
    <v-card density="compact" style="min-height:250px">
        <v-toolbar density="compact" color="mutedbg">
            <v-toolbar-title><v-icon color="primary">mdi-group</v-icon> Modules</v-toolbar-title>

            <v-spacer></v-spacer>


            <v-menu density="compact">
                <template v-slot:activator="{ props }">
                    <v-btn v-bind="props" color="primary" variant="text" prepend-icon="mdi-plus">
                        Create module
                    </v-btn>
                </template>

                <!-- options for copy current and blank -->
                <v-list>
                    <v-list-subheader>From existing module</v-list-subheader>
                    <v-list-item @click="startNewModule('copy', selectedNodeName, selectedNodeRegistry)" prepend-icon="mdi-file-multiple">Copy current</v-list-item>
                    <v-list-item @click="startNewModule('extend', selectedNodeName, selectedNodeRegistry)" prepend-icon="mdi-source-fork">Extend current</v-list-item>
                    <v-list-subheader>From scratch</v-list-subheader>
                    <v-list-item @click="startNewModule('command/Command')" prepend-icon="mdi-console-line">Command</v-list-item>
                    <v-list-item @click="startNewModule('core/Event')" prepend-icon="mdi-alpha-e-circle">Event</v-list-item>
                    <v-list-item @click="startNewModule('core/functions/Function')" prepend-icon="mdi-function">Function</v-list-item>
                    <!--<v-list-item @click="startNewModule('core/Loop')" prepend-icon="mdi-sync">Loop</v-list-item>-->
                    <v-list-item @click="startNewModule('core/Graph')" prepend-icon="mdi-file">Module</v-list-item>
                    <v-list-item @click="startNewModule('scene/SceneLoop')" prepend-icon="mdi-source-branch-sync">Scene Loop</v-list-item>
                </v-list>
            </v-menu>

            <v-text-field v-model="nodeLibrarySearch" placeholder="Filter" prepend-inner-icon="mdi-magnify" variant="underlined"></v-text-field>
        </v-toolbar>

        <ConfirmActionPrompt :max-width="400" :contained="true" ref="confirmModuleDelete" description="Are you sure you want to delete the {filename} module?" actionLabel="Delete module" @confirm="(params) => requestModuleDelete(params.path)" color="delete"></ConfirmActionPrompt>

        <v-card-text style="height: 300px; overflow-y: auto;">
            <div class="tiles pb-8">
                <v-card v-for="(node, idx) in listedNodes.scenes" :key="idx" :class="'tile mr-2 pb-2 mb-2'+(node.selected?' module-selected':'')" elevation="7" color="primary" variant="tonal" @click="$emit('load-node', node.fullPath)" density="compact">
                    <v-card-title class="text-caption font-weight-bold pb-0">{{ node.filename }}</v-card-title>
                    <v-card-subtitle class="text-caption">{{ node.path }}</v-card-subtitle>
                    <v-icon @click.stop="deleteModule(node.fullPath, node.filename)" size="x-small" class="module-card-icon">mdi-close-circle-outline</v-icon>
                </v-card>
                <v-card 
                v-for="(node, idx) in listedNodes.templates" :key="idx" :class="'tile mr-2 mb-2 pb-2 position-relative'+(node.selected?' module-locked-selected':'')" elevation="7" :color="node.selected ? 'locked_node' : 'locked_node'" variant="tonal" @click="$emit('load-node', node.fullPath)" density="compact">
                    <v-card-title class="text-caption font-weight-bold pb-0">{{ node.filename }}</v-card-title>
                    <v-card-subtitle class="text-caption">{{ node.path }}</v-card-subtitle>
                    <v-icon size="x-small" class="module-card-icon">mdi-lock</v-icon>
                </v-card>
            </div>
        </v-card-text>
    </v-card>

    <v-dialog v-model="newModuleDialog" :max-width="600" :contained="true" @keydown.esc="newModuleDialog = false">
        <v-card>
            <v-card-title>
                <v-icon :icon="newModule.icon" size="small" class="mr-2"></v-icon>
                Create new {{ newModule.label }}</v-card-title>
            <v-card-text>
                <v-alert v-if="newModule.nodes" density="compact" color="primary" variant="outlined" icon="mdi-graph-outline" class="mt-0 mb-4">
                    <span class="text-caption text-muted">You are creating a new module from a selection of {{ newModule.nodes.nodes.length }} nodes.</span>
                </v-alert>
                <v-alert v-else-if="newModule.type === 'extend'" density="compact" color="primary" variant="outlined" icon="mdi-information-outline" class="mt-0 mb-4">
                    <span class="text-caption text-muted">You are extending from <span class="text-primary">{{ newModule.original_registry }}</span></span>
                </v-alert>
                <v-alert v-else-if="newModule.type === 'copy'" density="compact" color="primary" variant="outlined" icon="mdi-information-outline" class="mt-0 mb-4">
                    <span class="text-caption text-muted">You are copying from <span class="text-primary">{{ newModule.original_registry }}</span></span>
                </v-alert>
                <v-form v-model="newModuleValid" @submit.prevent="createModule">

                    <v-text-field 
                        v-model="newModule.name" 
                        :rules="newModuleNameRules" 
                        label="Name" 
                        messages="Module title"
                        @keydown.enter="createModule"
                    ></v-text-field>
                    <v-text-field 
                        v-model="newModule.registry" 
                        :rules="newModuleRegistryRules" 
                        label="Registry" 
                        messages="Node registry path. (e.g., path/to/my/modules/$N) - $N will be substituted with a name generated from the title."
                        @keydown.enter="createModule"
                    ></v-text-field>
                </v-form>
            </v-card-text>
            <v-card-actions>
                <v-btn @click="newModuleDialog = false" color="muted" prepend-icon="mdi-cancel">
                    Cancel
                </v-btn>
                <v-spacer></v-spacer>
                <v-btn @click="createModule" color="primary" prepend-icon="mdi-check-circle-outline">
                    Continue
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>

</template>

<script>

import ConfirmActionPrompt from './ConfirmActionPrompt.vue';

export default {
    name: "NodeEditorLibrary",
    components: {
        ConfirmActionPrompt
    },
    data() {
        return {
            nodeLibrarySearch: '',
            library: [],
            newModuleNameRules: [
                v => !!v || 'Required',
            ],
            newModuleRegistryRules: [
                v => !!v || 'Required',
                v => this.validateRegistry(v) || this.newModuleRegistryRulesError,
            ],
            newModuleRegistryRulesError: "New module registry cannot be the same as the selected node registry",
            newModuleValid: false,
            newModuleDialog: false,
            newModule: {
                name: '',
                registry: '',
                type: '',
                nodes: null,
                icon: '',
                label: '',
                original_registry: null,
                copy_from: null,
                extend_from: null,
            }
        }
    },
    props: {
        scene: Object,
        appConfig: Object,
        templates: Object,
        generationOptions: Object,
        selectedNodePath: String,
        selectedNodeRegistry: String,
        selectedNodeName: String,
        maxNodesListed: {
            type: Number,
            default: 20
        }
    },
    inject: [
        'getWebsocket', 
        'registerMessageHandler', 
        'unregisterMessageHandler',
        'setEnvCreative',
        'setEnvScene',
        'getSelectedNodes',
    ],
    emits: ['create-node', 'load-node'],
    computed: {
        listedNodes() {
            /*
            first we want to turn the library list of paths into node objects
            that contain the filename and a shortened relative path

            paths will come in like:

            "scenes/infinity-quest/nodes/select-actor-for-turn.json"
            "templates/graphs/library/scene/select-actor-for-turn.json"
            "src/talemate/agents/director/modules/auto-direction.json"
            "src/talemate/game/engine/nodes/modules/scene/creative-loop.json"

            so if we get one that starts with "scenes" we classify the node as a scene node
            and the path can be the second part of the path (e.g. "infinity-quest")

            if it starts with "templates" we classify it as a third party template or
            template override.

            if it starts with src its a core module

            here we take everything after library and before the filename
            */

            // First process all paths into node objects
            let nodes = this.library.map(path => {
                // Normalize path separators to forward slashes for consistent processing
                const normalizedPath = path.replace(/\\/g, '/');
                const parts = normalizedPath.split('/');
                const filename = parts[parts.length - 1].replace('.json', '');

                if (normalizedPath.startsWith('scenes/')) {
                    return {
                        type: 'scene',
                        path: parts[1], // e.g. "infinity-quest"
                        filename,
                        fullPath: path, // Keep original path for backend communication
                        selected: path === this.selectedNodePath,
                        searchValue: `${filename} (${parts[1]})` // for search and display
                    };
                } else if (normalizedPath.startsWith('src/talemate/agents/')) {
                    //  core agent modules
                    const agentName = parts[3];
                    
                    return {
                        type: 'template',
                        path: agentName,
                        filename,
                        fullPath: path, // Keep original path for backend communication
                        selected: path === this.selectedNodePath,
                        searchValue: `${filename} (${agentName}) agent` // for search and display
                    };

                } else {
                    // For templates, take everything after '/modules/' and before filename
                    const libraryIndex = parts.indexOf('modules');
                    const relativePath = parts.slice(libraryIndex + 1, -1).join('/');

                    return {
                        type: 'template',
                        path: relativePath,
                        filename,
                        fullPath: path, // Keep original path for backend communication
                        selected: path === this.selectedNodePath,
                        searchValue: `${filename} (${relativePath})` // for search and display
                    };
                }
            }).filter(node => node !== null);

            console.log({nodes});

            // apply filter from search
            if (this.nodeLibrarySearch) {
                const searchTerm = this.nodeLibrarySearch.toLowerCase();
                nodes = nodes.filter(node =>
                    node.searchValue.toLowerCase().includes(searchTerm) ||
                    node.path.toLowerCase().includes(searchTerm)
                );
            }

            // apply maxNodesListed
            if (nodes.length > this.maxNodesListed) {
                nodes = nodes.slice(0, this.maxNodesListed);
            }

            // Group nodes by type
            return {
                scenes: nodes.filter(node => node.type === 'scene'),
                templates: nodes.filter(node => node.type === 'template')
            };

        }
    },
    methods: {

        typeToIcon(type) {
            switch(type) {
                case 'copy': return 'mdi-file-multiple';
                case 'extend': return 'mdi-source-fork';
                case 'command/Command': return 'mdi-console-line';
                case 'core/Event': return 'mdi-alpha-e-circle';
                case 'core/functions/Function': return 'mdi-function';
                case 'core/Graph': return 'mdi-file';
                case 'scene/SceneLoop': return 'mdi-source-branch-sync';
                default: return 'mdi-graph-outline';
            }
        },

        typeToLabel(type) {
            switch(type) {
                case 'copy': return 'Copy';
                case 'extend': return 'Extension';
                case 'command/Command': return 'Command';
                case 'core/Event': return 'Event';
                case 'core/functions/Function': return 'Function';
                case 'core/Graph': return 'Module';
                case 'scene/SceneLoop': return 'Scene Loop';
                default: return 'Module';
            }
        },

        validateRegistry(registry) {
            // if newModule.type is extend then the new registry
            // path cannot be the same as the selected node registry
            if(this.newModule.type === 'extend' && registry === this.selectedNodeRegistry) {
                return false;
            }
            return true;
        },

        startNewModule(type, name, registry) {
            this.newModule = {
                name: name || '',
                registry: registry || '',
                type: type,
                nodes: this.getSelectedNodes(),
                icon: this.typeToIcon(type),
                label: this.typeToLabel(type),
                original_registry: null,
                copy_from: null,
                extend_from: null,
            };
            this.newModuleDialog = true;

            // copy and extend type will always null the nodes property
            if(type === 'copy' || type === 'extend') {
                this.newModule.nodes = null;
                this.newModule.original_registry = this.selectedNodeRegistry;
                if(type === 'copy') {
                    this.newModule.copy_from = this.selectedNodePath;
                } else if(type === 'extend') {
                    this.newModule.extend_from = this.selectedNodePath;
                }
            }
        },

        deleteModule(path, filename) {
            this.$refs.confirmModuleDelete.initiateAction({path: path, filename: filename});
        },

        createModule() {
            console.log("Creating node", this.newModule);
            
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'create_mode_module',
                name: this.newModule.name,
                copy_from: this.newModule.copy_from,
                extend_from: this.newModule.extend_from,
                module_type: this.newModule.type,
                registry: this.newModule.registry,
                nodes: this.newModule.nodes,
            }));

            this.newModuleDialog = false;
        },

        requestModuleDelete(path) {
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'delete_node_module',
                path: path,
            }));
        },
        requestNodeLibrary() {
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'request_node_library',
            }));
        },

        handleMessage(message) {
            if(message.type !== 'node_editor') {
                return;
            }

            if(message.action === 'node_library') {
                this.library = message.data;
            } else if(message.action === 'created_node_module') {
                this.requestNodeLibrary();
            } else if(message.action === 'deleted_node_module') {
                this.requestNodeLibrary();
                // select the first node in the list
                console.log("Selected node path", this.selectedNodePath, message.path);
                if(this.selectedNodePath === message.path) {
                    if(this.listedNodes.scenes.length > 0) {
                        this.$emit('load-node', this.listedNodes.scenes[0].fullPath);
                    } else if(this.listedNodes.templates.length > 0) {
                        this.$emit('load-node', this.listedNodes.templates[0].fullPath);
                    } else {
                        this.$emit('load-node', '');
                    }
                }
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.requestNodeLibrary();
    },
    
    beforeUnmount() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}

</script>

<style scoped>
/* flud flex tiles with fixed width */
.tiles {
    display: flex;
    flex-wrap: wrap;
    justify-content: left;
    overflow: hidden;
}

.module-card-icon {
    position: absolute;
    right: 3px;
    top: 3px;
}

.module-locked-selected {
    border-width: 1px;
    border-color: rgb(var(--v-theme-locked_node_selected));
}

.module-selected {
    border-width: 1px;
    border-color: rgb(var(--v-theme-scene_node_selected));
}

</style>