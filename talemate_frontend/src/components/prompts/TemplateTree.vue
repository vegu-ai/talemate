<template>
    <v-treeview
        :items="treeItems"
        item-title="name"
        item-value="path"
        open-on-click
        activatable
        :activated="modelValue ? [modelValue] : []"
        @update:activated="onActivated"
        :opened="openedFolders"
        @update:opened="openedFolders = $event"
        density="compact"
        color="primary"
    >
        <template #prepend="{ item }">
            <v-icon v-if="item.isDirectory" size="small">mdi-folder-outline</v-icon>
            <v-icon v-else size="small">mdi-file-document-outline</v-icon>
        </template>
        <template #title="{ item }">
            <span :class="{ 'text-grey': isMuted(item) }">
                {{ item.name }}
            </span>
            <v-chip
                v-if="showSource && item.sourceGroup && !item.isDirectory"
                size="x-small"
                label
                class="ml-2"
                :color="getSourceColor(item.sourceGroup)"
                variant="tonal"
            >
                {{ item.sourceGroup }}
            </v-chip>
        </template>
        <template #append="{ item }">
            <slot name="item-append" :item="item"></slot>
        </template>
    </v-treeview>
</template>

<script>
export default {
    name: 'TemplateTree',
    props: {
        templates: {
            type: Array,
            default: () => []
        },
        showSource: {
            type: Boolean,
            default: false
        },
        mutedItems: {
            type: Array,
            default: () => []
        },
        modelValue: {
            type: String,
            default: null
        },
        prioritizeScene: {
            type: Boolean,
            default: false
        }
    },
    emits: ['update:modelValue', 'select'],
    data() {
        return {
            openedFolders: []
        };
    },
    computed: {
        treeItems() {
            // Build tree structure from flat template list
            // Templates have: uid, agent, name, source_group, available_in
            // Templates with '/' in their name should create nested folder structure
            const agentMap = {};

            for (const template of this.templates) {
                // Use 'scene' as the agent/category when agent is empty (scene templates)
                const agent = template.agent || 'scene';
                // For scene templates with empty agent, the UID should be scene.{name}
                const uid = template.uid || `scene.${template.name}`;

                if (!agentMap[agent]) {
                    agentMap[agent] = {
                        name: agent,
                        path: agent,
                        isDirectory: true,
                        children: []
                    };
                }

                // Check if template.name contains '/' (subdirectory template)
                if (template.name.includes('/')) {
                    // Build nested folder structure
                    const parts = template.name.split('/');
                    const templateBaseName = parts.pop(); // Last part is the actual template name

                    // Navigate/create the folder hierarchy
                    let currentLevel = agentMap[agent].children;
                    let currentPath = agent;

                    for (const folderName of parts) {
                        currentPath = `${currentPath}/${folderName}`;
                        let folder = currentLevel.find(item => item.isDirectory && item.name === folderName);

                        if (!folder) {
                            folder = {
                                name: folderName,
                                path: currentPath,
                                isDirectory: true,
                                children: []
                            };
                            currentLevel.push(folder);
                        }
                        currentLevel = folder.children;
                    }

                    // Add the template to the deepest folder
                    currentLevel.push({
                        name: templateBaseName,
                        path: uid,
                        uid: uid,
                        isDirectory: false,
                        sourceGroup: template.source_group,
                        availableIn: template.available_in || [],
                        existsInGroup: template.exists_in_group
                    });
                } else {
                    // Regular template without subdirectories
                    agentMap[agent].children.push({
                        name: template.name,
                        path: uid,
                        uid: uid,
                        isDirectory: false,
                        sourceGroup: template.source_group,
                        availableIn: template.available_in || [],
                        existsInGroup: template.exists_in_group
                    });
                }
            }

            // Sort agents and their children recursively
            const sortChildren = (items) => {
                items.sort((a, b) => {
                    // Directories first, then alphabetical
                    if (a.isDirectory && !b.isDirectory) return -1;
                    if (!a.isDirectory && b.isDirectory) return 1;
                    return a.name.localeCompare(b.name);
                });
                for (const item of items) {
                    if (item.children) {
                        sortChildren(item.children);
                    }
                }
            };

            const items = Object.values(agentMap).sort((a, b) => {
                // Optionally prioritize 'scene' folder at top
                if (this.prioritizeScene) {
                    if (a.name === 'scene') return -1;
                    if (b.name === 'scene') return 1;
                }
                return a.name.localeCompare(b.name);
            });
            for (const item of items) {
                sortChildren(item.children);
            }

            return items;
        }
    },
    watch: {
        templates: {
            immediate: true,
            handler() {
                // Auto-expand all folders on initial load
                if (this.openedFolders.length === 0 && this.treeItems.length > 0) {
                    this.openedFolders = this.treeItems.map(item => item.path);
                }
            }
        }
    },
    methods: {
        isMuted(item) {
            if (item.isDirectory) return false;
            return this.mutedItems.includes(item.uid);
        },
        getSourceColor(sourceGroup) {
            switch (sourceGroup) {
                case 'scene':
                    return 'warning';
                case 'user':
                    return 'success';
                case 'default':
                    return 'grey';
                default:
                    return 'primary';
            }
        },
        findItemByPath(items, path) {
            // Recursively search through nested children to find an item by path
            for (const item of items) {
                if (item.path === path) {
                    return item;
                }
                if (item.children) {
                    const found = this.findItemByPath(item.children, path);
                    if (found) return found;
                }
            }
            return null;
        },
        onActivated(activated) {
            const path = activated.length > 0 ? activated[0] : null;

            // Find the selected item recursively
            let selectedItem = null;
            if (path) {
                selectedItem = this.findItemByPath(this.treeItems, path);
                // If it's a directory, don't emit select
                if (selectedItem && selectedItem.isDirectory) {
                    return;
                }
            }

            this.$emit('update:modelValue', path);
            if (selectedItem) {
                this.$emit('select', selectedItem);
            }
        }
    }
};
</script>

<style scoped>
</style>
