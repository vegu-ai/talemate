<template>
    <v-card>
        <v-card-title>
            <v-icon class="mr-2">mdi-file-code-outline</v-icon>
            Prompts
        </v-card-title>
        <v-card-subtitle>
            Manage prompt templates and inspect prompts sent to the LLM.
        </v-card-subtitle>

        <v-card-text>
            <!-- Top-level tabs -->
            <v-tabs :model-value="effectiveMainTab" @update:model-value="onMainTabChange" color="primary" class="mb-4">
                <v-tab value="prompts">
                    <v-icon start>mdi-message-text-outline</v-icon>
                    Prompts
                    <v-chip
                        v-if="openPrompts.length > 0"
                        size="x-small"
                        class="ml-2"
                        color="primary"
                    >{{ openPrompts.length }}</v-chip>
                </v-tab>
                <v-tab value="templates">
                    <v-icon start>mdi-file-document-multiple-outline</v-icon>
                    Template Files
                </v-tab>
                <v-tab :disabled="!sceneLoaded" value="context-review">
                    <v-icon start>mdi-view-split-horizontal</v-icon>
                    Scene Context
                </v-tab>
            </v-tabs>

            <v-window :model-value="effectiveMainTab">
                <!-- Template Files Tab -->
                <v-window-item value="templates">
                    <!-- Loading indicator for initial data -->
                    <div v-if="loadingGroups && groups.length === 0" class="d-flex justify-center align-center pa-8">
                        <v-progress-circular indeterminate color="primary" size="48"></v-progress-circular>
                    </div>

                    <template v-else>
                        <v-tabs v-model="activeTab" color="secondary">
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
                                <v-tooltip activator="parent" location="top">Create a new template group</v-tooltip>
                            </v-tab>
                        </v-tabs>

                        <v-window v-model="activeTab">
                            <!-- Active tab -->
                            <v-window-item value="active">
                                <ActiveTab
                                    ref="activeTabRef"
                                    :groups="groups"
                                    :templates="templates"
                                    :loading="loadingTemplates"
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
                                    ref="groupTab_scene"
                                    group="scene"
                                    :is-scene="true"
                                    @deleted="onGroupDeleted"
                                />
                            </v-window-item>

                            <!-- Group tabs -->
                            <v-window-item
                                v-for="group in editableGroups"
                                :key="group.name"
                                :value="group.name"
                            >
                                <GroupTab
                                    :ref="`groupTab_${group.name}`"
                                    :group="group.name"
                                    @deleted="onGroupDeleted"
                                />
                            </v-window-item>
                        </v-window>
                    </template>
                </v-window-item>

                <!-- Prompts Tab -->
                <v-window-item value="prompts">
                    <div v-if="openPrompts.length === 0" class="text-center pa-8 text-grey">
                        <v-icon size="64" class="mb-4">mdi-message-text-outline</v-icon>
                        <p>No prompts open.</p>
                        <p class="text-caption">Click on a prompt in the sidebar to view its details here.</p>
                    </div>

                    <template v-else>
                        <v-tabs v-model="activePromptIndex" color="secondary">
                            <v-tab
                                v-for="(prompt, index) in openPrompts"
                                :key="prompt.num"
                                :value="index"
                            >
                                <span class="mr-2">#{{ prompt.num }}</span>
                                <span class="text-caption text-truncate" style="max-width: 150px;">{{ prompt.agent_action }}</span>
                                <v-btn
                                    icon
                                    size="x-small"
                                    variant="text"
                                    class="ml-2"
                                    @click.stop="closePrompt(index)"
                                >
                                    <v-icon size="small">mdi-close</v-icon>
                                </v-btn>
                            </v-tab>
                        </v-tabs>

                        <v-window v-model="activePromptIndex">
                            <v-window-item
                                v-for="(prompt, index) in openPrompts"
                                :key="prompt.num"
                                :value="index"
                            >
                                <PromptDetailView
                                    :prompt="prompt"
                                    @navigate-to-template="handleNavigateToTemplate"
                                />
                            </v-window-item>
                        </v-window>
                    </template>
                </v-window-item>

                <!-- Context Review Tab -->
                <v-window-item value="context-review">
                    <SceneContextReviewInline
                        :visible="mainTab === 'context-review'"
                        :agent-status="agentStatus"
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

        <!-- Toast notification -->
        <v-snackbar
            v-model="showToast"
            :color="toastColor"
            :timeout="5000"
            location="top"
        >
            {{ toastMessage }}
        </v-snackbar>
    </v-card>
</template>

<script>
import ActiveTab from './ActiveTab.vue';
import GroupTab from './GroupTab.vue';
import PromptDetailView from './PromptDetailView.vue';
import SceneContextReviewInline from '../SceneContextReviewInline.vue';

export default {
    name: 'PromptsView',
    components: {
        ActiveTab,
        GroupTab,
        PromptDetailView,
        SceneContextReviewInline,
    },
    props: {
        visible: {
            type: Boolean,
            default: false
        },
        prompts: {
            type: Array,
            default: () => []
        },
        agentStatus: {
            type: Object,
            default: null
        },
        mainTab: {
            type: String,
            default: 'prompts'
        }
    },
    emits: ['clear-prompts', 'update:mainTab'],
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'scene'
    ],
    data() {
        return {
            // Local-only tab (for context-review which isn't synced to the menu)
            internalMainTab: null,
            // Open prompts state
            openPrompts: [],
            activePromptIndex: 0,
            // Template files tab state
            activeTab: 'active',
            groups: [],
            templates: [],
            groupPriority: [],
            templateSources: {},
            sceneLoaded: false,
            showNewGroupDialog: false,
            newGroupName: '',
            newGroupFormValid: false,
            // Loading states
            loadingGroups: false,
            loadingTemplates: false,
            // Toast notification
            showToast: false,
            toastMessage: '',
            toastColor: 'error',
            // Pending navigation from sidebar
            pendingTemplateSelection: null
        };
    },
    computed: {
        effectiveMainTab() {
            return this.internalMainTab || this.mainTab;
        },
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
        mainTab() {
            // When the parent syncs a new tab value, clear internal override
            this.internalMainTab = null;
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
        onMainTabChange(value) {
            if (value === 'context-review') {
                // Local-only tab, don't sync to menu
                this.internalMainTab = value;
            } else {
                this.internalMainTab = null;
                this.$emit('update:mainTab', value);
            }
        },
        // Handle opening a prompt from PromptsMenu
        handleOpenPrompt(prompt) {
            // Check if prompt is already open
            const existingIndex = this.openPrompts.findIndex(p => p.num === prompt.num);
            if (existingIndex >= 0) {
                // Already open, just switch to it
                this.activePromptIndex = existingIndex;
            } else {
                // Add to open prompts
                this.openPrompts.push(prompt);
                this.activePromptIndex = this.openPrompts.length - 1;
            }
            // Switch to Prompts tab
            this.$emit('update:mainTab', 'prompts');
        },

        // Close a prompt tab
        closePrompt(index) {
            this.openPrompts.splice(index, 1);
            // Adjust active index if needed
            if (this.activePromptIndex >= this.openPrompts.length) {
                this.activePromptIndex = Math.max(0, this.openPrompts.length - 1);
            }
        },

        // Handle navigation to template from PromptDetailView
        handleNavigateToTemplate(templateUid) {
            // Ignore null/undefined template UIDs
            if (!templateUid) {
                return;
            }

            // Find the template in the resolved templates list
            const template = this.templates.find(t => t.uid === templateUid);

            if (!template) {
                // Template not found - show notification and switch to templates tab anyway
                this.showNotification(`Template "${templateUid}" not found`, 'warning');
                this.$emit('update:mainTab', 'templates');
                return;
            }

            // Use the existing navigateToTemplate method with the template's source group
            this.navigateToTemplate(templateUid, template.source_group);
        },

        // Navigate to a specific template (called from sidebar)
        navigateToTemplate(uid, sourceGroup) {
            // Ensure we're on the Template Files tab
            this.$emit('update:mainTab', 'templates');

            // Validate sourceGroup - fallback to 'active' if undefined or invalid
            if (!sourceGroup) {
                this.activeTab = 'active';
                this.pendingTemplateSelection = uid;
                this.$nextTick(() => {
                    this.selectPendingTemplate();
                });
                return;
            }

            // "default" has no dedicated tab - use "active" tab instead
            const targetTab = sourceGroup === 'default' ? 'active' : sourceGroup;

            // Validate that the target tab exists (active, scene, or an editable group)
            const validTabs = ['active', 'scene', ...this.editableGroups.map(g => g.name)];
            const finalTab = validTabs.includes(targetTab) ? targetTab : 'active';

            // Switch to the target tab
            this.activeTab = finalTab;

            // Store pending selection to be handled after tab switch
            this.pendingTemplateSelection = uid;

            // Wait for the tab switch to complete, then try to select the template
            this.$nextTick(() => {
                this.selectPendingTemplate();
            });
        },

        // Select the pending template in the current tab
        selectPendingTemplate() {
            if (!this.pendingTemplateSelection) return;

            const uid = this.pendingTemplateSelection;
            this.pendingTemplateSelection = null;

            if (this.activeTab === 'active') {
                // ActiveTab ref
                const activeTabRef = this.$refs.activeTabRef;
                if (activeTabRef) {
                    const template = this.templates.find(t => t.uid === uid);
                    if (template) {
                        activeTabRef.selectedTemplatePath = uid;
                        activeTabRef.expandAndSelectTemplate(template);
                    }
                }
            } else {
                // Find the ref for GroupTab instances
                const groupTabRef = this.$refs[`groupTab_${this.activeTab}`];
                if (groupTabRef) {
                    const template = groupTabRef.groupTemplates?.find(t => t.uid === uid);
                    if (template) {
                        groupTabRef.selectedTemplatePath = uid;
                        groupTabRef.expandAndSelectTemplate(template);
                    }
                }
            }
        },

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

        // Toast notification helper
        showNotification(message, color = 'error') {
            this.toastMessage = message;
            this.toastColor = color;
            this.showToast = true;
        },

        // WebSocket request methods
        requestGroups() {
            this.loadingGroups = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'list_groups'
            }));
        },
        requestTemplates() {
            this.loadingTemplates = true;
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

        onGroupDeleted() {
            this.activeTab = 'active';
        },

        // Clear prompts (emit to parent)
        clearPrompts() {
            this.$emit('clear-prompts');
        },

        // Message handler
        handleMessage(data) {
            if (data.type !== 'prompts') return;

            switch (data.action) {
                case 'list_groups':
                    this.loadingGroups = false;
                    this.groups = data.data.groups || [];
                    this.sceneLoaded = data.data.scene_loaded || false;
                    // Use the actual priority order from backend config
                    if (data.data.group_priority) {
                        this.groupPriority = data.data.group_priority;
                    }
                    break;

                case 'list_templates':
                    this.loadingTemplates = false;
                    this.templates = data.data.templates || [];
                    break;

                case 'get_template':
                    if (data.data.error) {
                        console.error('Error getting template:', data.data.error);
                        this.showNotification(`Failed to load template: ${data.data.error}`);
                    } else if (this.$refs.activeTabRef) {
                        this.$refs.activeTabRef.setTemplateContent(data.data.content || '');
                    }
                    break;

                case 'set_group_priority':
                    if (data.data.success) {
                        // Refresh groups and templates
                        this.requestGroups();
                        this.requestTemplates();
                    } else if (data.data.error) {
                        console.error('Error setting group priority:', data.data.error);
                        this.showNotification(`Failed to update priority: ${data.data.error}`);
                    }
                    break;

                case 'set_template_source':
                    if (data.data.success) {
                        this.requestTemplates();
                        // Reload preview if the changed template is currently selected
                        if (this.$refs.activeTabRef && data.data.uid) {
                            const selectedTemplate = this.$refs.activeTabRef.selectedTemplate;
                            if (selectedTemplate && selectedTemplate.uid === data.data.uid) {
                                this.requestTemplate({ uid: data.data.uid, group: null });
                            }
                        }
                    } else if (data.data.error) {
                        console.error('Error setting template source:', data.data.error);
                        this.showNotification(`Failed to set template source: ${data.data.error}`);
                    }
                    break;

                case 'create_group':
                    if (data.data.success) {
                        // Backend adds new group to priority, just refresh
                        this.requestGroups();
                        this.showNotification('Group created successfully', 'success');
                    } else if (data.data.error) {
                        console.error('Error creating group:', data.data.error);
                        this.showNotification(`Failed to create group: ${data.data.error}`);
                    }
                    break;

                case 'delete_group':
                    if (data.data.success) {
                        this.requestGroups();
                        this.requestTemplates();
                        this.showNotification('Group deleted successfully', 'success');
                    } else if (data.data.error) {
                        console.error('Error deleting group:', data.data.error);
                        this.showNotification(`Failed to delete group: ${data.data.error}`);
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
