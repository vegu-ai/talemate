<template>
    <v-card>
        <v-card-title>
            <v-icon class="mr-2">mdi-file-code-outline</v-icon>
            Prompt Templates
        </v-card-title>
        <v-card-subtitle>
            Manage prompt template groups and configure resolution priority.
        </v-card-subtitle>

        <v-card-text>
            <v-tabs v-model="activeTab" color="primary">
                <v-tab value="active">
                    <v-icon start>mdi-checkbox-marked-circle-outline</v-icon>
                    Active
                </v-tab>

                <!-- Scene tab: only visible when scene is loaded -->
                <v-tab v-if="sceneLoaded" value="scene">
                    <v-icon start>mdi-book-open-variant</v-icon>
                    scene
                </v-tab>

                <!-- Editable groups (user + custom) -->
                <v-tab
                    v-for="group in editableGroups"
                    :key="group.name"
                    :value="group.name"
                >
                    <v-icon start v-if="group.name === 'user'">mdi-account</v-icon>
                    <v-icon start v-else>mdi-folder-outline</v-icon>
                    {{ group.name }}
                </v-tab>

                <!-- New group button -->
                <v-tab value="__new__" @click.stop="showNewGroupDialog = true">
                    <v-icon>mdi-plus</v-icon>
                </v-tab>
            </v-tabs>

            <v-window v-model="activeTab">
                <!-- Active tab -->
                <v-window-item value="active">
                    <ActiveTab
                        ref="activeTab"
                        :groups="groups"
                        :templates="templates"
                        :group-priority="groupPriority"
                        :template-sources="templateSources"
                        :scene-loaded="sceneLoaded"
                        @update:priority="setGroupPriority"
                        @set-template-source="setTemplateSource"
                        @request-template="requestTemplate"
                    />
                </v-window-item>

                <!-- Scene tab -->
                <v-window-item v-if="sceneLoaded" value="scene">
                    <GroupTab
                        group="scene"
                        :is-scene="true"
                    />
                </v-window-item>

                <!-- Group tabs -->
                <v-window-item
                    v-for="group in editableGroups"
                    :key="group.name"
                    :value="group.name"
                >
                    <GroupTab
                        :group="group.name"
                    />
                </v-window-item>
            </v-window>
        </v-card-text>

        <!-- New group dialog -->
        <v-dialog v-model="showNewGroupDialog" max-width="400">
            <v-card>
                <v-card-title>Create New Group</v-card-title>
                <v-card-text>
                    <v-form ref="newGroupForm" v-model="newGroupFormValid" @submit.prevent="createGroup">
                        <v-text-field
                            v-model="newGroupName"
                            label="Group name"
                            :rules="[
                                v => !!v || 'Name is required',
                                v => !groupExists(v) || 'Group already exists',
                                v => validateGroupName(v)
                            ]"
                            required
                            autofocus
                            hint="No special characters: < > : / \\ | ? *"
                        ></v-text-field>
                    </v-form>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn
                        color="grey"
                        variant="text"
                        @click="showNewGroupDialog = false"
                    >
                        Cancel
                    </v-btn>
                    <v-btn
                        color="primary"
                        variant="tonal"
                        :disabled="!newGroupFormValid"
                        @click="createGroup"
                    >
                        Create
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </v-card>
</template>

<script>
import ActiveTab from './ActiveTab.vue';
import GroupTab from './GroupTab.vue';

export default {
    name: 'PromptsView',
    components: {
        ActiveTab,
        GroupTab
    },
    props: {
        visible: {
            type: Boolean,
            default: false
        }
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'scene'
    ],
    data() {
        return {
            activeTab: 'active',
            groups: [],
            templates: [],
            groupPriority: [],
            templateSources: {},
            sceneLoaded: false,
            showNewGroupDialog: false,
            newGroupName: '',
            newGroupFormValid: false
        };
    },
    computed: {
        editableGroups() {
            // Filter out scene and default, return user + custom groups
            return this.groups.filter(g =>
                g.name !== 'scene' && g.name !== 'default'
            );
        }
    },
    watch: {
        visible: {
            immediate: true,
            handler(newVal) {
                if (newVal) {
                    this.requestGroups();
                    this.requestTemplates();
                }
            }
        },
        activeTab(newVal) {
            // Reset to 'active' if trying to open __new__ tab
            if (newVal === '__new__') {
                this.$nextTick(() => {
                    this.activeTab = 'active';
                });
            }
        }
    },
    methods: {
        // Validation methods
        validateGroupName(value) {
            if (value == null) return true;
            if (/[<>:"/\\|?*]/.test(value)) {
                return 'Name contains invalid characters';
            }
            return true;
        },
        groupExists(name) {
            return this.groups.some(g => g.name === name);
        },

        // WebSocket request methods
        requestGroups() {
            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'list_groups'
            }));
        },
        requestTemplates() {
            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'list_templates'
            }));
        },
        requestTemplate({ uid, group }) {
            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'get_template',
                uid,
                group
            }));
        },
        setGroupPriority(priority) {
            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'set_group_priority',
                priority
            }));
            // Optimistic update
            this.groupPriority = priority;
        },
        setTemplateSource({ uid, group }) {
            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'set_template_source',
                uid,
                group
            }));
            // Optimistic update
            if (group === null) {
                delete this.templateSources[uid];
            } else {
                this.templateSources[uid] = group;
            }
            // Refresh templates to get updated resolution
            this.$nextTick(() => {
                this.requestTemplates();
            });
        },
        createGroup() {
            if (!this.newGroupFormValid || !this.newGroupName) return;

            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'create_group',
                name: this.newGroupName
            }));

            this.showNewGroupDialog = false;
            this.newGroupName = '';
        },

        // Message handler
        handleMessage(data) {
            if (data.type !== 'prompts') return;

            switch (data.action) {
                case 'list_groups':
                    this.groups = data.data.groups || [];
                    this.sceneLoaded = data.data.scene_loaded || false;
                    // Use the actual priority order from backend config
                    if (data.data.group_priority) {
                        this.groupPriority = data.data.group_priority;
                    }
                    break;

                case 'list_templates':
                    this.templates = data.data.templates || [];
                    break;

                case 'get_template':
                    if (data.data.error) {
                        console.error('Error getting template:', data.data.error);
                    } else if (this.$refs.activeTab) {
                        this.$refs.activeTab.setTemplateContent(data.data.content || '');
                    }
                    break;

                case 'set_group_priority':
                    if (data.data.success) {
                        // Refresh groups and templates
                        this.requestGroups();
                        this.requestTemplates();
                    }
                    break;

                case 'set_template_source':
                    if (data.data.success) {
                        this.requestTemplates();
                        // Reload preview if the changed template is currently selected
                        if (this.$refs.activeTab && data.data.uid) {
                            const selectedTemplate = this.$refs.activeTab.selectedTemplate;
                            if (selectedTemplate && selectedTemplate.uid === data.data.uid) {
                                this.requestTemplate({ uid: data.data.uid, group: null });
                            }
                        }
                    } else if (data.data.error) {
                        console.error('Error setting template source:', data.data.error);
                    }
                    break;

                case 'create_group':
                    if (data.data.success) {
                        // Backend adds new group to priority, just refresh
                        this.requestGroups();
                    } else if (data.data.error) {
                        console.error('Error creating group:', data.data.error);
                    }
                    break;

                case 'delete_group':
                    if (data.data.success) {
                        this.requestGroups();
                        this.requestTemplates();
                    }
                    break;

                case 'save_template':
                case 'delete_template':
                case 'create_template':
                    // Refresh templates when any group tab saves/deletes
                    // This keeps the Active tab in sync
                    if (data.data.success) {
                        this.requestTemplates();
                    }
                    break;
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.requestGroups();
        this.requestTemplates();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
};
</script>

<style scoped>
</style>
