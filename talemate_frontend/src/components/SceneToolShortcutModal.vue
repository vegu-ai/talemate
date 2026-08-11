<template>
    <v-dialog v-model="dialog" max-width="600">
        <v-card>
            <v-card-title>{{ editing ? 'Edit Shortcut' : 'Add Shortcut' }}</v-card-title>
            <v-card-text>
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
                <v-spacer></v-spacer>
                <v-btn color="cancel" variant="text" @click="dialog = false">Cancel</v-btn>
                <v-btn color="primary" variant="text" prepend-icon="mdi-check-circle-outline" @click="save" :disabled="!isValid">Save</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import { v4 as uuidv4 } from 'uuid';
import IconPicker from './IconPicker.vue';

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
    },
    inject: ['appConfig', 'saveAppConfig'],
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
        }
    },
    computed: {
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
    },
}
</script>
