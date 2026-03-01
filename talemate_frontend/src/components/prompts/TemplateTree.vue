<template>
    <v-treeview
        style="width: 600px;"
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
            <v-icon v-else size="small" :color="item.isUnresolvable ? 'warning' : item.isOverride ? 'success' : undefined">mdi-file-document-outline</v-icon>
        </template>
        <template #title="{ item }">
            <span :class="{ 'text-grey': isMuted(item) }">
                {{ abbreviateName(item.name) }}
                <v-tooltip v-if="item.name.length > 40" activator="parent" location="top">{{ item.name }}</v-tooltip>
            </span>
            <v-chip
                v-if="item.isDirectory && item.hasOverride"
                size="x-small"
                label
                color="success"
                variant="tonal"
                class="ml-1"
            >
                overrides
            </v-chip>
            <v-chip
                v-if="item.isDirectory && item.hasOutdated"
                size="x-small"
                label
                color="warning"
                variant="tonal"
                class="ml-1"
            >
                outdated
            </v-chip>
            <v-chip
                v-if="item.isOutdated && !item.isDirectory"
                size="x-small"
                label
                color="warning"
                variant="tonal"
                class="ml-1"
            >
                outdated
                <v-tooltip activator="parent" location="top">
                    This override is older than the default template and may need updating.
                </v-tooltip>
            </v-chip>
            <v-chip
                v-if="item.isUnresolvable && !item.isDirectory"
                size="x-small"
                label
                color="grey"
                variant="tonal"
                class="ml-1"
            >
                group not active
                <v-tooltip activator="parent" location="top">
                    This template only exists in an inactive group. Activate the group to use it.
                </v-tooltip>
            </v-chip>
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
        // Build tree and compute folders with overrides in a single pass
        treeData() {
            // Build tree structure from flat template list
            // Templates have: uid, agent, name, source_group, available_in
            // Templates with '/' in their name should create nested folder structure
            const agentMap = {};

            for (const template of this.templates) {
                // Use 'scene' as the agent/category when agent is empty (scene templates)
                const agent = template.agent || 'scene';
                // For scene templates with empty agent, the UID should be scene.{name}
                const uid = template.uid || `scene.${template.name}`;
                const isOverride = this.isOverrideTemplate(template);

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
                        existsInGroup: template.exists_in_group,
                        isOverride: isOverride,
                        isOutdated: template.is_outdated || false,
                        isUnresolvable: template.is_unresolvable || false
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
                        existsInGroup: template.exists_in_group,
                        isOverride: isOverride,
                        isOutdated: template.is_outdated || false,
                        isUnresolvable: template.is_unresolvable || false
                    });
                }
            }

            // Single pass: sort and propagate hasOverride up to parent folders
            const foldersWithOverrides = [];

            const processChildren = (items) => {
                items.sort((a, b) => {
                    // Directories first, then alphabetical
                    if (a.isDirectory && !b.isDirectory) return -1;
                    if (!a.isDirectory && b.isDirectory) return 1;
                    return a.name.localeCompare(b.name);
                });

                let hasOverride = false;
                let hasOutdated = false;
                for (const item of items) {
                    if (item.children) {
                        // Recurse into children first (bottom-up)
                        const result = processChildren(item.children);
                        if (result.hasOverride) {
                            hasOverride = true;
                            item.hasOverride = true;
                            foldersWithOverrides.push(item.path);
                        }
                        if (result.hasOutdated) {
                            hasOutdated = true;
                            item.hasOutdated = true;
                        }
                    } else {
                        if (item.isOverride) {
                            hasOverride = true;
                        }
                        if (item.isOutdated) {
                            hasOutdated = true;
                        }
                    }
                }
                return { hasOverride, hasOutdated };
            };

            const items = Object.values(agentMap).sort((a, b) => {
                // Optionally prioritize 'scene' folder at top
                if (this.prioritizeScene) {
                    if (a.name === 'scene') return -1;
                    if (b.name === 'scene') return 1;
                }
                return a.name.localeCompare(b.name);
            });

            // Process each top-level agent folder
            for (const item of items) {
                const result = processChildren(item.children);
                if (result.hasOverride) {
                    item.hasOverride = true;
                    foldersWithOverrides.push(item.path);
                }
                if (result.hasOutdated) {
                    item.hasOutdated = true;
                }
            }

            return { items, foldersWithOverrides };
        },
        treeItems() {
            return this.treeData.items;
        },
        foldersWithOverrides() {
            return this.treeData.foldersWithOverrides;
        }
    },
    watch: {
        foldersWithOverrides: {
            immediate: true,
            handler(newFolders) {
                this.openedFolders = newFolders;
            }
        }
    },
    methods: {
        // Check if a template is an override based on available_in
        isOverrideTemplate(template) {
            const availableIn = template.available_in || [];
            if (availableIn.length === 0) return false;
            if (availableIn.length === 1 && availableIn[0] === 'default') return false;
            return true;
        },
        isMuted(item) {
            if (item.isDirectory) return false;
            if (item.isUnresolvable) return true;
            return this.mutedItems.includes(item.uid);
        },
        abbreviateName(name) {
            if (name.length <= 40) return name;
            const start = name.substring(0, 18);
            const end = name.substring(name.length - 19);
            return `${start}...${end}`;
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
                // If it's a directory or unresolvable, don't emit select
                if (selectedItem && (selectedItem.isDirectory || selectedItem.isUnresolvable)) {
                    return;
                }
            }

            this.$emit('update:modelValue', path);
            if (selectedItem) {
                this.$emit('select', selectedItem);
            }
        },
        // Expand all parent folders for a given template uid
        expandToTemplate(uid) {
            if (!uid) return;

            // uid format: "agent.template-name" or "agent.folder/subfolder/template-name"
            const dotIndex = uid.indexOf('.');
            if (dotIndex === -1) return;

            const agent = uid.substring(0, dotIndex);
            const templatePath = uid.substring(dotIndex + 1);

            // Collect all folder paths that need to be opened
            const foldersToOpen = [agent];

            if (templatePath.includes('/')) {
                const parts = templatePath.split('/');
                parts.pop(); // Remove the template name itself
                let currentPath = agent;
                for (const folder of parts) {
                    currentPath = `${currentPath}/${folder}`;
                    foldersToOpen.push(currentPath);
                }
            }

            // Merge with existing opened folders (avoid duplicates)
            const newOpened = [...new Set([...this.openedFolders, ...foldersToOpen])];
            this.openedFolders = newOpened;
        }
    }
};
</script>

<style scoped>
</style>
