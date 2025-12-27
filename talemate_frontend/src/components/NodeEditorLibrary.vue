<template>
    <v-card density="compact" style="min-height:250px">
        <v-toolbar density="compact" color="mutedbg">
            <v-toolbar-title><v-icon color="primary">mdi-file-tree</v-icon> Modules
                <v-chip color="primary" variant="tonal" size="small" class="ml-2">
                    {{ treeStats.filtered }} / {{ treeStats.total }}
                </v-chip>
            </v-toolbar-title>
            <v-chip v-if="!sceneReadyForNodeEditing" color="warning" variant="text" size="x-small" prepend-icon="mdi-alert-circle-outline">
                Save project to be able to create modules
            </v-chip>
            <v-menu density="compact">
                <template v-slot:activator="{ props }">
                    <v-btn :disabled="!canCreateModules" v-bind="props" color="primary" variant="text" prepend-icon="mdi-plus">
                        Create module
                    </v-btn>
                </template>

                <v-list>
                    <v-list-subheader>From existing module</v-list-subheader>
                    <v-list-item @click="startNewModule('copy', selectedNodeName, selectedNodeRegistry)" prepend-icon="mdi-file-multiple">Copy current</v-list-item>
                    <v-list-item @click="startNewModule('extend', selectedNodeName, selectedNodeRegistry)" prepend-icon="mdi-source-fork">Extend current</v-list-item>
                    <v-list-subheader>From scratch</v-list-subheader>
                    <v-list-item @click="startNewModule('command/Command')" prepend-icon="mdi-console-line">Command</v-list-item>
                    <v-list-item @click="startNewModule('core/Event')" prepend-icon="mdi-alpha-e-circle">Event</v-list-item>
                    <v-list-item @click="startNewModule('core/functions/Function')" prepend-icon="mdi-function">Function</v-list-item>
                    <v-list-item @click="startNewModule('core/Graph')" prepend-icon="mdi-file">Module</v-list-item>
                    <v-list-item @click="startNewModule('scene/SceneLoop')" prepend-icon="mdi-source-branch-sync">Scene Loop</v-list-item>
                    <v-list-item @click="startNewModule('util/packaging/Package')" prepend-icon="mdi-package-variant">Package</v-list-item>
                    <v-list-item @click="startNewModule('agents/director/DirectorChatAction')" prepend-icon="mdi-bullhorn">Director Action</v-list-item>
                    <v-list-item @click="startNewModule('agents/AgentWebsocketHandler')" prepend-icon="mdi-robot-happy">Agent Websocket Handler</v-list-item>
                </v-list>
            </v-menu>
        </v-toolbar>

        <v-list-item v-if="selectedNodeName" density="compact" class="mx-2 mt-2" border rounded>
            <v-list-item-title class="text-caption text-primary font-weight-bold text-truncate">
                {{ selectedNodeName }}
                <v-tooltip activator="parent" location="bottom">{{ selectedNodeName }}</v-tooltip>
            </v-list-item-title>
            <v-list-item-subtitle class="text-caption text-muted text-truncate" style="font-size: 0.7rem !important;">
                {{ selectedNodeRegistry }}
                <v-tooltip activator="parent" location="bottom">{{ selectedNodeRegistry }}</v-tooltip>
            </v-list-item-subtitle>
        </v-list-item>

        <v-toolbar density="compact" color="transparent">
            <v-text-field
                class="mx-3 my-1"
                v-model="nodeLibrarySearchInput"
                placeholder="Filter"
                prepend-inner-icon="mdi-magnify"
                variant="underlined"
                hide-details="auto"
            ></v-text-field>
        </v-toolbar>

        <ConfirmActionPrompt :max-width="400" :contained="true" ref="confirmModuleDelete" description="Are you sure you want to delete the {filename} module?" actionLabel="Delete module" @confirm="(params) => requestModuleDelete(params.path)" color="delete"></ConfirmActionPrompt>

        <v-card-text>
            <v-treeview
                :key="nodeLibrarySearch"
                :items="treeItems"
                item-title="title"
                item-value="id"
                activatable
                open-on-click
                density="compact"
                :opened="treeOpen"
                :activated="treeActive"
                color="primary"
                @update:activated="onTreeActive"
            >
                <template #prepend="{ item }">
                    <v-icon size="small" v-if="item.isDir">mdi-folder</v-icon>
                    <v-icon size="small" v-else :color="item.color">{{ item.icon || 'mdi-file' }}</v-icon>
                </template>
                <template #title="{ item }">
                    <span :class="item.selected ? 'text-primary font-weight-medium' : ''">{{ item.title }}</span>
                </template>
                <template #append="{ item }">
                    <v-icon v-if="!item.isDir && item.deletable" size="x-small" class="module-card-icon" @click.stop="deleteModule(item.fullPath, item.title)">mdi-close-circle-outline</v-icon>
                    <v-tooltip v-else-if="!item.isDir && item.locked && item.selected && canCreateModules" text="Copy to scene">
                        <template v-slot:activator="{ props }">
                            <v-icon v-bind="props" size="x-small" class="module-card-icon" @click.stop="copyModuleToScene(item)">mdi-content-copy</v-icon>
                        </template>
                    </v-tooltip>
                    <v-icon v-else-if="!item.isDir && item.locked" size="x-small" class="module-card-icon">mdi-lock</v-icon>
                </template>
            </v-treeview>
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
                        :disabled="creatingNode"
                        v-model="newModule.name" 
                        :rules="newModuleNameRules" 
                        label="Name" 
                        messages="Module title"
                        @keydown.enter="createModule"
                    ></v-text-field>
                    <v-text-field 
                        :disabled="creatingNode"
                        v-model="newModule.registry" 
                        :rules="newModuleRegistryRules" 
                        label="Registry" 
                        messages="Node registry path. (e.g., path/to/my/modules/$N) - $N will be substituted with a name generated from the title."
                        @keydown.enter="createModule"
                    ></v-text-field>
                    <v-text-field 
                        :disabled="creatingNode"
                        v-model="newModule.filename" 
                        label="Filename" 
                        messages="Filename for the module file (without path)"
                        @keydown.enter="createModule"
                    ></v-text-field>
                </v-form>
            </v-card-text>
            <v-card-actions>
                <v-btn :disabled="creatingNode" @click="newModuleDialog = false" color="muted" prepend-icon="mdi-cancel">
                    Cancel
                </v-btn>
                <v-spacer></v-spacer>
                <v-btn :disabled="creatingNode" @click="createModule" color="primary" prepend-icon="mdi-check-circle-outline">
                    Continue
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>

</template>

<script>

import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import { debounce } from 'lodash';

export default {
    name: "NodeEditorLibrary",
    components: {
        ConfirmActionPrompt
    },
    data() {
        return {
            nodeLibrarySearchInput: '',
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
            creatingNode: false,
            newModule: {
                name: '',
                registry: '',
                filename: '',
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
    created() {
        this.updateSearchDebounced = debounce((value) => {
            this.nodeLibrarySearch = value;
        }, 200);
    },
    watch: {
        nodeLibrarySearchInput(newValue) {
            this.updateSearchDebounced(newValue);
        },
        'newModule.name'(newValue, oldValue) {
            // Auto-update filename when name changes, but only if filename matches what it should be for the old name
            if (newValue && this.newModuleDialog) {
                const expectedFilename = this.normalizeNodeFilename(newValue);
                const expectedOldFilename = oldValue ? this.normalizeNodeFilename(oldValue) : '';
                // Only auto-update if filename is empty or matches what it should be for the old name
                if (!this.newModule.filename || this.newModule.filename === expectedOldFilename) {
                    this.newModule.filename = expectedFilename;
                }
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
        sceneReadyForNodeEditing: Boolean,
        nodeDefinitions: {
            type: Object,
            default: () => ({})
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

        moduleDefinitionByPath() {
            const byPath = {};
            for (const [registry, nodeDef] of Object.entries(this.nodeDefinitions)) {
                if(!nodeDef.module_path) {
                    continue;
                }
                byPath[nodeDef.module_path] = nodeDef;
            }
            return byPath;
        },

        canCreateModules() {
            return this.sceneReadyForNodeEditing;
        },

        flatLeaves() {
            // Merge scenes and templates into one filtered, ordered array
            const nodes = this.listedNodes;
            return [...nodes.scenes, ...nodes.templates];
        },

        treeItems() {
            // Display-only simplified grouping
            // - Scene modules under "scene"
            // - Agent modules under "agents/<agent>"
            // - Core modules under "core"
            const groups = {};
            const ensureGroup = (id, title) => {
                if (!groups[id]) {
                    groups[id] = { id, title, isDir: true, children: [] };
                }
                return groups[id];
            };

            for (const node of this.flatLeaves) {
                const normalizedPath = node.fullPath.replace(/\\/g, '/').replace(/\.json$/, '');
                const parts = normalizedPath.split('/');

                let groupId = 'templates';
                let groupTitle = 'templates';

                if (node.isSceneModule) {
                    groupId = 'scene';
                    groupTitle = 'scene';
                } else if (node.isAgentModule) {
                    // src/talemate/agents/<agent>/modules/... -> agent name at parts[3]
                    const agentName = parts[3];
                    groupId = `agents/${agentName}`;
                    groupTitle = `agents/${agentName}`;
                } else if (node.isCoreModule) {
                    groupId = 'core';
                    groupTitle = 'core';
                } else if (normalizedPath.startsWith('templates/modules/')) {
                    // For templates/modules/{project}/..., use the project as the group
                    const projectDir = parts[2]; // templates/modules/{project}
                    groupId = `templates/modules/${projectDir}`;
                    groupTitle = `installed/${projectDir}`;
                }

                const group = ensureGroup(groupId, groupTitle);
                const filename = parts[parts.length - 1];
                const icon = this.getModuleIcon(node.fullPath);
                group.children.push({
                    id: normalizedPath,
                    title: this.getModuleName(node.fullPath) || filename.replace(/-/g, ' '),
                    isDir: false,
                    fullPath: node.fullPath,
                    selected: node.selected,
                    deletable: node.isSceneModule,
                    locked: !node.isSceneModule,
                    icon: icon,
                    color: this.iconToColor(icon),
                });
            }

            // sort children by title
            Object.values(groups).forEach(g => g.children.sort((a, b) => a.title.localeCompare(b.title)));

            // stable order: scene, agents/* (alphabetical), core, templates/modules/* (alphabetical), templates
            const root = [];
            if (groups['scene']) root.push(groups['scene']);
            const agentGroups = Object.keys(groups).filter(k => k.startsWith('agents/')).sort();
            for (const k of agentGroups) root.push(groups[k]);
            if (groups['core']) root.push(groups['core']);
            const templateModuleGroups = Object.keys(groups).filter(k => k.startsWith('templates/modules/')).sort();
            for (const k of templateModuleGroups) root.push(groups[k]);
            if (groups['templates']) root.push(groups['templates']);
            return root;
        },

        treeStats() {
            return {
                total: this.library.length,
                filtered: this.flatLeaves.length,
            };
        },

        treeOpen() {
            // If filtering, expand all groups that contain matches
            if (this.nodeLibrarySearch && this.nodeLibrarySearch.length > 1) {
                return this.treeItems
                    .filter(g => g.isDir && g.children && g.children.length)
                    .map(g => g.id);
            }

            if (!this.selectedNodePath) return [];
            const normalized = this.selectedNodePath.replace(/\\/g, '/');
            if (normalized.startsWith('scenes/')) {
                return ['scene'];
            } else if (normalized.startsWith('src/talemate/agents/')) {
                const agent = normalized.split('/')[3];
                return [`agents/${agent}`];
            } else if (normalized.startsWith('src/talemate/')) {
                return ['core'];
            }
            return ['templates'];
        },

        treeActive() {
            if (!this.selectedNodePath) return [];
            return [this.selectedNodePath.replace(/\\/g, '/').replace(/\.json$/, '')];
        },

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

            let selectedNode = null;

            // First process all paths into node objects
            let nodes = this.library.map(path => {
                // Normalize path separators to forward slashes for consistent processing
                const normalizedPath = path.replace(/\\/g, '/');
                const parts = normalizedPath.split('/');
                const filename = parts[parts.length - 1].replace('.json', '');
                const filenameParts = filename.split('-').join(' ');
     
                const libraryIndex = parts.indexOf('modules');
                const relativePath = parts.slice(libraryIndex + 1, -1).join('/');
                const isCoreModule = normalizedPath.startsWith('src/talemate/');
                const isAgentModule = normalizedPath.startsWith('src/talemate/agents/');
                const isSceneModule = normalizedPath.startsWith('scenes/');

                let _path = relativePath;
                let searchValue = `${filename} (${parts[1]}) ${filenameParts}`;
                let type = (isSceneModule) ? 'scene' : 'template';
                let subType = (isCoreModule) ? 'core' : 'template';

                if(isSceneModule) {
                    _path = parts[1];
                    subType = 'scene';
                } else if (isAgentModule) {
                    const agentName = parts[3];
                    searchValue = `${searchValue} (${agentName}) $agent`;
                    _path = agentName;
                } else if(!isCoreModule) {
                    subType = 'template';
                    searchValue = `${searchValue} $template`;
                }

                return {
                    type: type,
                    path: _path,
                    isCoreModule,
                    isAgentModule,
                    subType,
                    isSceneModule,
                    filename,
                    fullPath: path, // Keep original path for backend communication
                    selected: path === this.selectedNodePath,
                    searchValue: searchValue // for search and display
                };

            }).filter(node => node !== null);

            const totalNodes = nodes.length;

            if(this.selectedNodePath) {
                selectedNode = nodes.find(node => node.fullPath === this.selectedNodePath);
            }

            // drop the selected node from the list
            if(selectedNode) {
                nodes = nodes.filter(node => node.fullPath !== this.selectedNodePath);
            }


            // apply filter from search
            if (this.nodeLibrarySearch && this.nodeLibrarySearch.length > 1) {
                const searchTerm = this.nodeLibrarySearch.toLowerCase();
                nodes = nodes.filter(node =>
                    node.searchValue.toLowerCase().includes(searchTerm) ||
                    node.path.toLowerCase().includes(searchTerm)
                );
            }

            // no limit with tree view; show all

            // selected node is always added regardless of filtering
            if(selectedNode) {
                nodes.unshift(selectedNode);
            }
            

            // sort by filename
            nodes.sort((a, b) => a.filename.localeCompare(b.filename));

            // Group nodes by type
            return {
                scenes: nodes.filter(node => node.type === 'scene'),
                templates: nodes.filter(node => node.type === 'template'),
                totalNodeCount: totalNodes,
                filteredNodeCount: nodes.length,
                hiddenNodeCount: totalNodes - nodes.length,
            };

        }
    },
    methods: {
        onTreeActive(newActive) {
            if (!newActive || newActive.length === 0) {
                return;
            }
            const id = newActive[0];
            // Find the leaf item with this id by walking the tree
            const findItem = (items) => {
                for (const it of items) {
                    if (it.id === id) return it;
                    if (it.isDir && it.children && it.children.length) {
                        const found = findItem(it.children);
                        if (found) return found;
                    }
                }
                return null;
            };
            const item = findItem(this.treeItems);
            if (item && !item.isDir && item.fullPath) {
                this.$emit('load-node', item.fullPath);
            }
        },

        copyModuleToScene(item) {
            // Prefill with current selected node's values (no transformations)
            const name = this.selectedNodeName || '';
            this.newModule = {
                name: name,
                registry: this.selectedNodeRegistry || '',
                filename: this.normalizeNodeFilename(name),
                type: 'copy',
                nodes: null,
                icon: this.typeToIcon('copy'),
                label: this.typeToLabel('copy'),
                original_registry: this.selectedNodeRegistry || null,
                copy_from: this.selectedNodePath || null,
                extend_from: null,
            };
            this.newModuleDialog = true;
        },

        typeToIcon(type) {
            switch(type) {
                case 'copy': return 'mdi-file-multiple';
                case 'extend': return 'mdi-source-fork';
                case 'command/Command': return 'mdi-console-line';
                case 'core/Event': return 'mdi-alpha-e-circle';
                case 'core/functions/Function': return 'mdi-function';
                case 'core/Graph': return 'mdi-file';
                case 'scene/SceneLoop': return 'mdi-source-branch-sync';
                case 'util/packaging/Package': return 'mdi-package-variant';
                case 'agents/director/DirectorChatAction': return 'mdi-bullhorn';
                case 'agents/AgentWebsocketHandler': return 'mdi-web-box';
                default: return 'mdi-graph-outline';
            }
        },

        getModuleIcon(fullPath) {
            if(!this.moduleDefinitionByPath[fullPath]) {
                return 'mdi-file';
            }
            const type = this.moduleDefinitionByPath[fullPath].base_type;
            return this.typeToIcon(type);
        },

        getModuleName(fullPath) {
            if(!this.moduleDefinitionByPath[fullPath]) {
                return null;
            }
            return this.moduleDefinitionByPath[fullPath].title;
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
                case 'agents/AgentWebsocketHandler': return 'Agent Websocket Handler';
                case 'agents/director/DirectorChatAction': return 'Director Chat Action';
                default: return 'Module';
            }
        },

        iconToColor(icon) {
            switch(icon) {
                case 'mdi-console-line': return 'highlight1';
                case 'mdi-alpha-e-circle': return 'yellow-darken-1';
                case 'mdi-function': return 'orange-lighten-1';
                case 'mdi-file': return 'grey';
                case 'mdi-package-variant': return 'green-lighten-1';
                case 'mdi-bullhorn': return 'director';
                case 'mdi-source-branch-sync': return 'highlight6';
                case 'mdi-web-box': return 'highlight7';
                default: return null;
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
            const moduleName = name || '';
            this.newModule = {
                name: moduleName,
                registry: registry || '',
                filename: this.normalizeNodeFilename(moduleName),
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

        normalizeNodeFilename(nodeName) {
            if (!nodeName) return '';
            return nodeName.toLowerCase().replace(/\s+/g, '-') + '.json';
        },

        createModule() {
            console.log("Creating node", this.newModule);
            this.creatingNode = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'node_editor',
                action: 'create_mode_module',
                name: this.newModule.name,
                filename: this.newModule.filename || this.normalizeNodeFilename(this.newModule.name),
                copy_from: this.newModule.copy_from,
                extend_from: this.newModule.extend_from,
                module_type: this.newModule.type,
                registry: this.newModule.registry,
                nodes: this.newModule.nodes,
            }));

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
                this.creatingNode = false;
                this.newModuleDialog = false;
            } else if(message.action === 'deleted_node_module') {
                this.requestNodeLibrary();
                // select the first node in the list, unless the first module is the one
                // that was just deleted (the listing may not have been updated yet)
                const firstModuleIsDeleted = (this.listedNodes.scenes.length > 0 && message.path === this.listedNodes.scenes[0].fullPath)
                if(this.selectedNodePath === message.path) {
                    if(this.listedNodes.scenes.length > 0 && !firstModuleIsDeleted) {
                        this.$emit('load-node', this.listedNodes.scenes[0].fullPath);
                    } else if(this.listedNodes.templates.length > 0) {
                        this.$emit('load-node', this.listedNodes.templates[0].fullPath);
                    } else {
                        this.$emit('load-node', '');
                    }
                }
            } else if(message.action === 'operation_done') {
                this.creatingNode = false;
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

/* Reduce left indent for nested tree items */
:deep(.v-treeview) {
    --indent-size: 12px;
}

</style>