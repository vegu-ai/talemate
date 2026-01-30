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
            const agentMap = {};

            for (const template of this.templates) {
                const agent = template.agent;
                if (!agentMap[agent]) {
                    agentMap[agent] = {
                        name: agent,
                        path: agent,
                        isDirectory: true,
                        children: []
                    };
                }

                agentMap[agent].children.push({
                    name: template.name,
                    path: template.uid,
                    uid: template.uid,
                    isDirectory: false,
                    sourceGroup: template.source_group,
                    availableIn: template.available_in || [],
                    existsInGroup: template.exists_in_group
                });
            }

            // Sort agents and their children
            const items = Object.values(agentMap).sort((a, b) => a.name.localeCompare(b.name));
            for (const item of items) {
                item.children.sort((a, b) => a.name.localeCompare(b.name));
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
        onActivated(activated) {
            const path = activated.length > 0 ? activated[0] : null;

            // Find the selected item
            let selectedItem = null;
            if (path) {
                for (const agent of this.treeItems) {
                    if (agent.path === path) {
                        // Agent folder selected - don't emit
                        return;
                    }
                    for (const template of agent.children) {
                        if (template.path === path) {
                            selectedItem = template;
                            break;
                        }
                    }
                    if (selectedItem) break;
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
