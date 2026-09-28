<template>
    <div :style="{ maxWidth: MAX_CONTENT_WIDTH }">
    <!-- edit template -->


    <!-- group -->
    <v-card v-if="group !== null && template === null">
        <v-card-title>
            <v-icon size="small" class="mr-2">mdi-group</v-icon>
            {{ toLabel(group.name) || 'New template group' }}
        </v-card-title>
        <v-card-text>
            <v-form ref="groupForm" v-model="groupFormValid">
                <v-row>
                    <v-col cols="4">
                        <v-text-field 
                        v-model="group.name" 
                        label="Group name" 
                        :rules="[v => !!v || 'Name is required', v => validateGroupName(v)]"
                        required
                        @update:model-value="groupDirty = true"
                        @blur="saveTemplateGroup"
                        hint="Invalid characters: &lt; &gt; : / \\ | ? *" 
                        >
                        </v-text-field>
                    </v-col>
                    <v-col cols="4">
                        <v-text-field 
                        v-model="group.author" 
                        label="Author" 
                        @update:model-value="groupDirty = true"
                        @blur="saveTemplateGroup"
                        :rules="[v => !!v || 'Author is required']"
                        required
                        >
                        </v-text-field>
                    </v-col>
                    <v-col cols="4">

                    </v-col>
                </v-row>
                <v-row>
                    <v-col cols="12">
                        <v-textarea 
                        v-model="group.description"
                        label="Description"
                        @update:model-value="groupDirty = true"
                        @blur="saveTemplateGroup"
                        hint="A short description of what this group is for."
                        auto-grow
                        rows="3">
                        </v-textarea>
                    </v-col>
                </v-row>
            </v-form>
        </v-card-text>
        <v-card-actions v-if="!group.uid">
            <v-spacer></v-spacer>
            <v-btn rounded="sm" prepend-icon="mdi-cube-scan" color="primary" @click.stop="saveTemplateGroup(true)" >
                Create Template Group
            </v-btn>
        </v-card-actions>
        <v-card-actions v-else>
            <ConfirmActionInline
                :actionLabel="'Remove group'"
                :confirmLabel="'Confirm removal'"
                :disabled="groupHasLocked"
                @confirm="removeTemplateGroup"
            />
            <div v-if="groupHasLocked" class="text-body-small text-muted ml-2">The group holds locked templates and cannot be removed.</div>
        </v-card-actions>
    </v-card>


    <v-card v-if="template !== null">
        <v-card-title v-if="template.uid">
            <v-icon size="small" class="mr-2">{{ iconForTemplate(template) }}</v-icon>
            {{ template.name  }}
            <v-chip label size="x-small" color="primary" class="ml-1">
                <strong class="mr-2 text-deep-purple-lighten-3">Group</strong>{{ toLabel(group.name) }}
            </v-chip>
            <v-chip label size="x-small" color="muted" class="ml-1">
                <strong class="mr-2 text-high-emphasis">Type</strong>{{ templateTypeTitle(template.template_type) }}
            </v-chip>
        </v-card-title>
        <v-card-title v-else>
            <v-icon size="small" class="mr-2">{{ iconForTemplate(template) }}</v-icon>
            New Template
            <v-chip label size="x-small" color="primary" class="ml-1">
                <strong class="mr-2 text-deep-purple-lighten-3">Group</strong>{{ toLabel(group.name) }}
            </v-chip>
            <v-chip label size="x-small" color="muted" class="ml-1" v-if="template.template_type">
                {{ templateTypeTitle(template.template_type) }}
            </v-chip>
        </v-card-title>
        <v-card-text>
            <v-alert v-if="externalChange" density="compact" variant="tonal" color="warning" icon="mdi-alert-circle-outline" class="mb-3">
                This template was changed elsewhere - by the help chat or another window - while you have unsaved edits here. Your edits overwrite that change when they save.
            </v-alert>
            <v-form ref="form" v-model="formValid">
                <div v-if="!template.uid">
                    <v-row>
                        <v-col cols="12" sm="6" xl="4" xxl="3">
                            <v-text-field 
                            v-model="template.name" 
                            label="Template name" 
                            :rules="[v => !!v || 'Name is required', v => validateTemplateName(v)]"
                            required
                            hint="No special characters allowed" 
                            >
                            </v-text-field>
                        </v-col>
                        <v-col cols="12" sm="6" xl="4" xxl="3">
                            <v-select
                            v-model="template.template_type"
                            @update:model-value="onTemplateTypeChange"
                            :items="templateTypes"
                            label="Template type">
                                <template v-slot:item="{ props, item }">
                                    <v-list-item v-bind="props" slim>
                                        <template v-slot:prepend>
                                            <v-icon :color="item.color" class="opacity-100">{{ item.icon }}</v-icon>
                                        </template>
                                    </v-list-item>
                                </template>
                                <template v-slot:selection="{ item }">
                                    <v-icon :color="item.color" size="small" class="mr-2">{{ item.icon }}</v-icon>
                                    {{ item.title }}
                                </template>
                            </v-select>
                        </v-col>
                    </v-row>
                </div>

                
                <v-alert v-if="template && templateTypeHelp(template.template_type)" :icon="iconForTemplate(template)" color="muted" variant="text" density="compact" class="mt-2 mb-2">
                    {{ templateTypeHelp(template.template_type) }}
                </v-alert>


                <!-- State Reinforcement Template -->
                <div v-if="template.template_type === 'state_reinforcement'">
                    <TemplateStateReinforcement 
                        ref="templateEditor"
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>


                <!-- Character Attribute Template -->
                <div v-else-if="template.template_type === 'character_attribute'">
                    <TemplateCharacterAttribute 
                        ref="templateEditor"
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Character Detail Template -->
                <div v-else-if="template.template_type === 'character_detail'">
                    <TemplateCharacterDetail 
                        ref="templateEditor"
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Spice Collection Template -->
                <div v-else-if="template.template_type === 'spices'">
                    <TemplateSpices
                        ref="templateEditor"
                        :immutableTemplate="template"
                        :templates="templates"
                        :scene-active="sceneActive"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Writing Style Template -->
                <div v-else-if="template.template_type === 'writing_style'">
                    <TemplateWritingStyle
                        ref="templateEditor"
                        :immutableTemplate="template"
                        :default-decision-checks="templates?.defaults?.writing_style?.decision_checks || []"
                        :scene-active="sceneActive"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Visual Style Template -->
                <div v-else-if="template.template_type === 'visual_style'">
                    <TemplateVisualStyle
                        ref="templateEditor"
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Visual Prompt Finalizer Template -->
                <div v-else-if="template.template_type === 'visual_finalizer'">
                    <TemplateVisualFinalizer
                        ref="templateEditor"
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Agent Persona Template -->
                <div v-else-if="template.template_type === 'agent_persona'">
                    <TemplateAgentPersona 
                        ref="templateEditor"
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Scene Type Template -->
                <div v-else-if="template.template_type === 'scene_type'">
                    <TemplateSceneType
                        ref="templateEditor"
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Scene Tool Shortcut Template -->
                <div v-else-if="template.template_type === 'scene_tool_shortcut'">
                    <TemplateSceneToolShortcut
                        ref="templateEditor"
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Theme Template -->
                <div v-else-if="template.template_type === 'theme'">
                    <TemplateTheme
                        ref="templateEditor"
                        :immutableTemplate="template"
                        :themeTemplates="themeTemplateChoices"
                        @update="(template) => applyAndSaveTemplate(template)"
                        @flush="(template) => saveTemplatePayload(template)"
                    />
                </div>

            </v-form>

        </v-card-text>
        <v-card-actions v-if="template.uid && !template.locked">
            <ConfirmActionInline
                :actionLabel="'Remove template'"
                :confirmLabel="'Confirm removal'"
                @confirm="removeTemplate"
            />
        </v-card-actions>
        <v-card-actions v-else-if="!template.uid && template.template_type !== null && template.name !== null">
            <v-btn rounded="sm" prepend-icon="mdi-cube-scan" color="primary" @click.stop="saveTemplate(true)" >
                Create template
            </v-btn>
        </v-card-actions>
    </v-card>

    <!-- no template selected -->
    <div v-else-if="template === null && group === null">
        <v-row>
            <v-col cols="12" lg="12" xl="8" xxl="6">
                <v-card>
                    <v-alert class="text-medium-emphasis" variant="text" icon="mdi-cube-scan">
                        Templates are used to facilitate the generation of content for your game. They can be used to define character attributes, character details, writing styles, and automated world or character state tracking.
                        <br><br>
                        Templates are managed in <span class="text-primary"><v-icon size="small">mdi-group</v-icon> groups.</span> Each group can contain multiple templates. When starting out, start by creating a new group and then add templates to it.
                        <br><br>
                        Templates are stored outside of individual games and will be available for all
                        games you run.
                    </v-alert>
                </v-card>

                <!-- Guidance card for users who only have default groups -->
                <v-card v-if="onlyDefaultGroupsExist" class="mt-6 mb-6 ml-4" elevation="3" color="muted" variant="tonal" style="max-width: 600px;">
                    <v-card-title>
                        <v-icon size="small" class="mr-2" color="primary">mdi-lightbulb-on</v-icon>
                        Get Started: Create Your Own Template Group
                    </v-card-title>
                    <v-card-text>
                        You currently have only the default template groups. To create your own custom templates, 
                        start by creating your own template group. This will allow you to organize your templates 
                        and keep them separate from the default ones.
                    </v-card-text>
                    <v-card-actions>
                        <v-btn @click="createNewGroup" color="primary" variant="text">
                            <v-icon start>mdi-plus</v-icon>
                            Create New Group
                        </v-btn>
                    </v-card-actions>
                </v-card>

                <v-card elevation="3" density="compact" class="mt-2" v-for="templateType in templateTypes" :key="templateType.value">
                    <v-card-title>
                        <v-icon size="small" class="mr-2" :color="templateType.color">{{ templateType.icon }}</v-icon>
                        {{ templateType.title }}
                    </v-card-title>
                    <v-card-text class="text-muted">
                        {{ templateType.help }}
                    </v-card-text>
                </v-card>
            </v-col>
        </v-row>
    </div>
    </div>

</template>

<script>

import ConfirmActionInline from './ConfirmActionInline.vue';
import ContextualGenerate from './ContextualGenerate.vue';
import TemplateWritingStyle from './TemplateWritingStyle.vue';
import TemplateVisualStyle from './TemplateVisualStyle.vue';
import TemplateVisualFinalizer from './TemplateVisualFinalizer.vue';
import TemplateAgentPersona from './TemplateAgentPersona.vue';
import TemplateStateReinforcement from './TemplateStateReinforcement.vue';
import TemplateCharacterAttribute from './TemplateCharacterAttribute.vue';
import TemplateCharacterDetail from './TemplateCharacterDetail.vue';
import TemplateSpices from './TemplateSpices.vue';
import TemplateSceneType from './TemplateSceneType.vue';
import TemplateSceneToolShortcut from './TemplateSceneToolShortcut.vue';
import TemplateTheme from './TemplateTheme.vue';
import { iconForTemplate, hydrateThemeTemplate } from '../utils/templateMappings.js';
import { templateTypeHelp, templateTypeItems, templateTypeTitle } from '../utils/templateTypes.js';
import { getActiveCodeEditorTheme } from '../utils/codeEditorTheme.js';
import { validateGroupName } from '../utils/sceneToolShortcuts.js';
import { adoptedTemplateUid } from '../utils/templateSaveEcho.js';
import { MAX_CONTENT_WIDTH } from '@/constants/layout';

export default {
    name: 'Templates',
    components: {
        ConfirmActionInline,
        ContextualGenerate,
        TemplateWritingStyle,
        TemplateVisualStyle,
        TemplateVisualFinalizer,
        TemplateAgentPersona,
        TemplateStateReinforcement,
        TemplateCharacterAttribute,
        TemplateCharacterDetail,
        TemplateSpices,
        TemplateSceneType,
        TemplateSceneToolShortcut,
        TemplateTheme,
    },
    props: {
        immutableTemplates: Object,
        sceneActive: {
            type: Boolean,
            default: false
        }
    },
    emits: [
        'selection-changed'
    ],
    watch: {
        immutableTemplates: {
            handler(val) {
                this.onTemplatesPushed(val);
            },
            immediate: true
        }
    },
    computed: {
        onlyDefaultGroupsExist() {
            if (!this.templates || !this.templates.managed || !this.templates.managed.groups) {
                return false;
            }
            
            const groups = this.templates.managed.groups;
            const defaultGroupNames = ['Human', 'default', 'legacy-state-reinforcements'];
            
            // Check if all existing groups are in the default list
            const allGroupsAreDefault = groups.every(group => 
                defaultGroupNames.includes(group.name)
            );
            
            // Only show guidance if there are groups and they're all defaults
            return groups.length > 0 && allGroupsAreDefault;
        },
        groupHasLocked() {
            return Object.values((this.group && this.group.templates) || {})
                .some((template) => template.locked);
        },
        themeTemplateChoices() {
            const groups = this.templates?.managed?.groups || [];
            return groups
                .map((group) => ({
                    uid: group.uid,
                    name: group.name || group.uid,
                    themes: Object.values(group.templates || {})
                        .filter((template) => template.template_type === 'theme'),
                }))
                .filter((group) => group.themes.length > 0);
        }
    },
    data() {
        return {
            MAX_CONTENT_WIDTH,
            filter: null,
            newName: null,
            newType: 'state_reinforcement',
            saveTimeout: null,
            deleteConfirm: false,
            groupFormValid: false,
            formValid: false,
            dirty: false,
            groupDirty: false,
            externalChange: false,
            adoptedSnapshot: null,
            templates: null,
            templateTypes: templateTypeItems(),
            template: null,
            group: null,
            deferredSelect: null,
            selectedGroups: [],
            selected: null,
        };
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'requestTemplates',
        'toLabel',
    ],
    methods: {
        onTemplatesPushed(val) {
            this.templates = val ? {...val} : null;

            if(this.deferredSelect) {
                let index = this.deferredSelect;
                this.deferredSelect = null;
                this.selectTemplate(index);
                return;
            }

            this.adoptSelection();
        },

        // the editor keeps the template object it was handed on selection, so a
        // push has to hand it the fresh one - otherwise its next save writes the
        // pre-push values back over whatever wrote them (the help chat, another
        // window). Unsaved edits here belong to the user: those are flagged
        // rather than discarded.
        adoptSelection() {
            const groups = this.templates?.managed?.groups || [];
            const group = (this.group && this.group.uid)
                ? groups.find((candidate) => candidate.uid === this.group.uid)
                : null;

            if (!group) {
                return;
            }

            const incoming = (this.template && this.template.uid)
                ? (group.templates || {})[this.template.uid] || null
                : null;

            if (this.editorDirty()) {
                // the push echoing this view's own save carries what it just
                // wrote - only a differing payload came from somewhere else
                if (incoming && JSON.stringify(incoming) !== this.adoptedSnapshot) {
                    this.externalChange = true;
                }
            } else if (incoming) {
                this.template = incoming;
                this.rememberAdopted();
            }

            // the group form binds straight onto this object and saves on blur,
            // so half-typed text lives here and nowhere else
            if (!this.groupDirty) {
                this.group = group;
            }
        },

        // baseline for telling a push that echoes this view's own save from one
        // carrying somebody else's write
        rememberAdopted() {
            this.adoptedSnapshot = this.template ? JSON.stringify(this.template) : null;
            this.externalChange = false;
        },

        // every template editor keeps its own copy and its own pending edit -
        // keystrokes since the last blur, an open color picker - and saves
        // through this component. One ref covers them all: only the editor for
        // the selected template type is rendered.
        editorDirty() {
            const editor = this.$refs.templateEditor;
            return this.dirty || !!(editor && editor.dirty);
        },

        uxSnapshot() {
            // what the templates tab shows, for the help agent's UX snapshot.
            // `dirty` gates the help agent's theme writes backend-side: the tab
            // saves the whole template it is on, so an unsaved edit here would
            // push the pre-change template back over an agent write.
            //
            // Reported off-screen too - an edit survives leaving the tab, and so
            // must the refusal it gates. The theme editor keeps its own dirty
            // flag (an open color picker, an unblurred notes field), which is
            // where a pending theme edit lives.
            return {
                tab: 'templates',
                dirty: this.editorDirty(),
                selected: (this.selected && this.selected[0]) || null,
                template_type: (this.template && this.template.template_type) || null,
            };
        },
        iconForTemplate,
        templateTypeHelp,
        templateTypeTitle,
        onTemplateTypeChange() {
            if(this.template && this.template.template_type === 'character_attribute') {
                if(!this.template.attribute)
                    this.template.attribute = this.template.name;
            } else if(this.template && this.template.template_type === 'character_detail') {
                if(!this.template.detail)
                    this.template.detail = this.template.name;
            } else if(this.template && this.template.template_type === 'scene_tool_shortcut') {
                if(!this.template.label)
                    this.template.label = this.template.name;
                if(!this.template.icon)
                    this.template.icon = iconForTemplate(this.template);
            } else if(this.template && this.template.template_type === 'theme') {
                hydrateThemeTemplate(this.template, this.$vuetify.theme.current.colors, this.$vuetify.theme.current.dark, getActiveCodeEditorTheme());
            }
        },

        validateTemplateName(value) {
            if(value == null)
                return true;
            
            // no special characters, return false if there are any
            if(value.match(/[^a-zA-Z0-9_ ]/)) {
                return "No special characters allowed";
            }
            return true
        },

        validateGroupName,

        selectTemplate(index) {
            if(index === '$DESELECTED') {
                this.group = null;
                this.template = null;
                this.selectedGroups = [];
                this.selected = null;
                this.dirty = false;
                this.groupDirty = false;
                return;
            } else if (index === '$CREATE_GROUP') {
                this.group = {
                    name: '',
                    author: '',
                    description: '',
                    templates: {},
                }
                this.groupDirty = false;
                this.template = null;
                this.selectedGroups = [];
                this.selected = null;
                return;
            } else if(!index) {
                this.template = null;
                this.selected = null;
                return;
            }

            // first find group by name
            let group_id = index.split('__')[0];
            let template_id = index.split('__')[1];

            const safeGroups = this.templates?.managed?.groups || [];
            let group = safeGroups.find(g => g.uid === group_id);

            if (!group) {
                return;
            }
            this.group = group;
            this.groupDirty = false;

            // Update selected groups
            const groupIndex = safeGroups.findIndex(g => g.uid === group_id);
            if(groupIndex !== -1) {
                this.selectedGroups = [groupIndex];
                // Emit update for parent component to sync with menu
                this.$emit('selection-changed', {
                    selectedGroups: this.selectedGroups,
                    selected: this.selected
                });
            }

            let template = null;
            if(template_id === '$CREATE') {
                template = {
                    template_type: null,
                    name: '',
                    group: group.uid,
                    priority: 1,
                    spices: [],
                }
                this.selected = null;
            } else if (template_id && !group.templates[template_id]) {
                this.deferredSelect = index;
                return;
            } else if (template_id && (!this.template || this.template.uid !== template_id)) {
                template = group.templates[template_id] || null;
                this.selected = [`${group_id}__${template_id}`];
                this.dirty = false;
            } else if (template_id && this.template && this.template.uid === template_id) {
                template = this.template;
            }

            this.template = template;
            this.rememberAdopted();
            
            // Emit update for parent component to sync with menu
            if(template_id) {
                this.$emit('selection-changed', {
                    selectedGroups: this.selectedGroups,
                    selected: this.selected
                });
            }
        },
        createNewGroup() {
            // Use the same pattern as selectTemplate with $CREATE_GROUP
            this.selectTemplate('$CREATE_GROUP');
        },

        // queue requests
        queueSaveTemplate(delay = 1500) {

            if(!this.template || !this.template.uid) {
                return;
            }

            if (this.saveTimeout !== null) {
                clearTimeout(this.saveTimeout);
            }

            this.dirty = true;

            this.saveTimeout = setTimeout(() => {
                this.saveTemplate();
            }, delay);
        },

        queueSaveGroup(delay = 1500) {

            if(!this.group || !this.group.uid) {
                return;
            }

            if (this.saveTimeout !== null) {
                clearTimeout(this.saveTimeout);
            }

            this.dirty = true;

            this.saveTimeout = setTimeout(() => {
                this.saveTemplateGroup();
            }, delay);
        },

        // requests 
        applyAndSaveTemplate(template, saveNew = false) {
            this.template = template;
            this.saveTemplate(saveNew);
        },

        // persist a template without making it the current selection - a flushed
        // edit belongs to the template the user has already navigated away from
        saveTemplatePayload(template) {
            if (!template || !template.uid) {
                return;
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_template',
                template: template
            }));
        },
        
        saveTemplate(saveNew) {

            if(!this.template || (!this.template.uid && !saveNew)) {
                return;
            }

            this.$refs.form.validate()

            if(!this.formValid) {
                // the editor cleared its own flag before emitting, so nothing
                // else records that the typed value never reached the backend
                this.dirty = true;
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_template',
                template: this.template
            }));
            // what was just sent is what the echo will carry - without this the
            // baseline stays on the pre-save values and the view's own echo
            // reads as somebody else's write
            this.rememberAdopted();
        },

        saveTemplateGroup(saveNew) {

            if(!this.group || (!this.group.uid && !saveNew)) {
                return;
            }

            this.$refs.groupForm.validate()

            if(!this.groupFormValid) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_template_group',
                group: this.group
            }));
        },

        removeTemplate() {
            this.deleteConfirm = false;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_template',
                template: this.template
            }));
        },

        removeTemplateGroup() {
            this.deleteConfirm = false;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_template_group',
                group: this.group
            }));
        },


        // responses
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action == 'template_saved') {
                this.dirty = false;
                const uid = adoptedTemplateUid(this.template, message.data.template);
                if (uid) {
                    this.template.uid = uid;
                    // the menu's re-select of the created template now finds the
                    // form already on that uid and leaves it alone, so the
                    // selection it stands for has to be recorded here
                    this.selected = [`${this.template.group}__${uid}`];
                }
                this.requestTemplates();
            } else if (message.action == 'template_deleted') {
                if (this.selected && this.selected[0] && this.selected[0].includes(message.data.template.uid)) {
                    this.template = null;
                    this.selected = null;
                }
                this.requestTemplates();
            } else if (message.action == 'template_group_saved') {
                this.dirty = false;
                this.groupDirty = false;
                if(this.group && !this.group.uid) {
                    this.group = message.data.group;
                }
                this.requestTemplates();
            } else if (message.action == 'template_group_deleted') {
                if (this.selectedGroups && this.selectedGroups.length > 0) {
                    const safeGroups = this.templates?.managed?.groups || [];
                    const deletedGroup = safeGroups[this.selectedGroups[0]];
                    if(deletedGroup && deletedGroup.uid == message.data.group.uid) {
                        this.group = null;
                        this.template = null;
                        this.selectedGroups = [];
                        this.selected = null;
                    }
                }
                this.requestTemplates();
            }
        },
    },
    mounted(){
        this.registerMessageHandler(this.handleMessage);
        this.requestTemplates();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
};
</script>
