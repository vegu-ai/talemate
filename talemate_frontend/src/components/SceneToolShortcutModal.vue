<template>
    <v-dialog v-model="dialog" max-width="600">
        <v-card>
            <v-card-title>{{ editing ? 'Edit Shortcut' : 'Add Shortcut' }}</v-card-title>
            <v-card-text>
                <v-alert v-if="templateSaved" type="success" variant="text" density="compact" class="mb-2">{{ templateSaved }}</v-alert>
                <v-alert v-if="templateError" type="error" variant="text" density="compact" class="mb-2">{{ templateError }}</v-alert>

                <v-select
                    v-model="actionId"
                    :items="actionItems"
                    label="Action"
                    prepend-inner-icon="mdi-play-box-outline"
                    no-data-text="Loading actions..."
                ></v-select>

                <v-text-field
                    ref="labelInput"
                    v-model="label"
                    label="Label"
                    hint="Shown in the scene tools menu."
                    :rules="[v => !!(v && v.trim()) || 'Label is required']"
                ></v-text-field>

                <v-textarea
                    v-model="instructions"
                    label="Instructions"
                    hint="Optional direction handed to the agent when the shortcut is used."
                    rows="3"
                    auto-grow
                    max-rows="6"
                ></v-textarea>

                <IconPicker ref="iconPicker" v-model="icon" @update:valid="iconValid = $event" />
            </v-card-text>
            <v-card-actions>
                <v-btn v-if="editing" color="delete" variant="text" prepend-icon="mdi-close-box-outline" @click="remove">Delete</v-btn>
                <v-btn v-if="editing" color="primary" variant="text" prepend-icon="mdi-cube-scan" @click="openTemplateDialog" :disabled="!isValid">Save as template</v-btn>
                <v-spacer></v-spacer>
                <v-btn color="cancel" variant="text" @click="dialog = false">Cancel</v-btn>
                <v-btn color="primary" variant="text" prepend-icon="mdi-check-circle-outline" @click="save" :disabled="!isValid">Save</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>

    <v-dialog v-model="templateDialog" max-width="480">
        <v-card>
            <v-card-title>Save as Template</v-card-title>
            <v-card-text>
                <v-combobox
                    v-model="templateGroupName"
                    :items="templateGroupNames"
                    label="Template group"
                    prepend-inner-icon="mdi-group"
                    hint="Pick a group or type a name to create a new one."
                    persistent-hint
                    :rules="[v => validateGroupName(v)]"
                ></v-combobox>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="cancel" variant="text" @click="templateDialog = false">Cancel</v-btn>
                <v-btn color="primary" variant="text" prepend-icon="mdi-cube-scan" @click="saveAsTemplate" :disabled="!templateGroupValid">Save template</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import { v4 as uuidv4 } from 'uuid';
import IconPicker from './IconPicker.vue';
import { shortcutAsTemplate, templateGroupByName, templateSaveTransition, validateGroupName } from '@/utils/sceneToolShortcuts';

const SECTION_LABELS = {
    narrator: 'Narrator',
    actor: 'Actor',
    director: 'Director',
    visual: 'Visual',
};

export default {
    name: 'SceneToolShortcutModal',
    components: {
        IconPicker,
    },
    props: {
        catalog: {
            type: Array,
            default: () => [],
        },
        templateGroups: {
            type: Array,
            default: () => [],
        },
    },
    inject: ['appConfig', 'saveAppConfig', 'getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
    data() {
        return {
            dialog: false,
            editing: false,
            uid: null,
            actionId: null,
            label: '',
            instructions: '',
            icon: '',
            iconValid: false,
            templateDialog: false,
            templateGroupName: '',
            templateSaved: null,
            templateError: null,
            pendingTemplateSave: null,
        }
    },
    computed: {
        templateGroupNames() {
            return this.templateGroups.map(group => group.name);
        },
        templateGroupValid() {
            const name = (this.templateGroupName || '').trim();
            return !!name && validateGroupName(name) === true;
        },
        actionItems() {
            return this.catalog.map(entry => ({
                title: `${this.sectionLabel(entry.section)} · ${entry.label}`,
                value: entry.id,
            }));
        },
        isValid() {
            return !!this.actionId && !!this.label.trim() && this.iconValid;
        },
    },
    watch: {
        dialog(value) {
            if (!value) {
                // a save the backend never echoed would otherwise still be
                // waiting the next time the modal is opened
                this.pendingTemplateSave = null;
                this.templateError = null;
                this.templateDialog = false;
                return;
            }
            // the picker stays mounted between openings, so re-opening with the
            // same icon emits no update:valid to mirror
            this.$nextTick(() => {
                if (this.$refs.iconPicker) {
                    this.iconValid = this.$refs.iconPicker.valid;
                }
            });
        },
    },
    methods: {
        validateGroupName,

        sectionLabel(section) {
            return SECTION_LABELS[section] || section;
        },

        storedShortcuts() {
            return this.appConfig()?.shortcuts?.scene_tools || {};
        },

        reset() {
            this.editing = false;
            this.uid = null;
            this.actionId = null;
            this.label = '';
            this.instructions = '';
            this.icon = '';
            this.iconValid = false;
            this.templateSaved = null;
            this.templateError = null;
            this.pendingTemplateSave = null;
        },

        open(section) {
            this.reset();
            const first = this.catalog.find(entry => entry.section === section);
            this.actionId = first ? first.id : null;
            this.dialog = true;
            this.$nextTick(() => {
                if (this.$refs.labelInput && this.$refs.labelInput.focus) {
                    this.$refs.labelInput.focus();
                }
            });
        },

        openEdit(shortcut) {
            this.reset();
            const stored = this.storedShortcuts()[shortcut.uid];
            this.editing = true;
            this.uid = stored.uid;
            this.actionId = stored.action_id;
            this.label = stored.label;
            this.instructions = stored.instructions;
            this.icon = stored.icon;
            this.dialog = true;
        },

        save() {
            const shortcut = {
                uid: this.editing ? this.uid : uuidv4(),
                action_id: this.actionId,
                label: this.label.trim(),
                icon: this.icon,
                instructions: this.instructions,
            };

            this.saveAppConfig((config) => {
                config.shortcuts.scene_tools[shortcut.uid] = shortcut;
            }, { label: 'scene tool shortcuts' });

            this.dialog = false;
        },

        remove() {
            const uid = this.uid;

            this.saveAppConfig((config) => {
                delete config.shortcuts.scene_tools[uid];
            }, { label: 'scene tool shortcuts' });

            this.dialog = false;
        },

        openTemplateDialog() {
            this.templateSaved = null;
            this.templateError = null;
            this.templateGroupName = '';
            this.templateDialog = true;
        },

        saveAsTemplate() {
            const groupName = (this.templateGroupName || '').trim();

            if (!this.templateGroupValid) {
                return;
            }

            const group = templateGroupByName(this.templateGroups, groupName);
            const template = shortcutAsTemplate({
                action_id: this.actionId,
                label: this.label,
                icon: this.icon,
                instructions: this.instructions,
            }, group ? group.uid : null, uuidv4());

            const requestId = uuidv4();

            this.templateError = null;
            this.templateDialog = false;

            if (group) {
                this.pendingTemplateSave = { template, groupName, requestId };
                this.sendSaveTemplate(template, requestId);
                return;
            }

            // a template can only be saved into a group the backend already
            // knows — create it first, minting its uid here so the echo can be
            // told apart from any other save of a group by that name
            const groupUid = uuidv4();
            this.pendingTemplateSave = { template, groupName, groupUid, requestId };
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_template_group',
                request_id: requestId,
                group: {
                    uid: groupUid,
                    name: groupName,
                    author: '',
                    description: '',
                    templates: {},
                },
            }));
        },

        sendSaveTemplate(template, requestId) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_template',
                request_id: requestId,
                template,
            }));
        },

        handleMessage(message) {
            const pending = this.pendingTemplateSave;
            const transition = templateSaveTransition(pending, message);

            if (transition.op === 'send-template') {
                this.pendingTemplateSave = { ...pending, template: transition.template };
                this.sendSaveTemplate(transition.template, pending.requestId);
            } else if (transition.op === 'complete') {
                this.pendingTemplateSave = null;
                this.templateSaved = `Saved to template group '${pending.groupName}'`;
            } else if (transition.op === 'fail') {
                this.pendingTemplateSave = null;
                this.templateError = transition.message;
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>
