<template>
    <v-row>
        <v-col cols="12" sm="8" xxl="5">
            <v-select
                v-model="template.action_id"
                :items="actionItems"
                label="Action"
                prepend-inner-icon="mdi-play-box-outline"
                :rules="[v => !!v || 'Action is required']"
                :color="dirty ? 'dirty' : ''"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                no-data-text="Loading actions..."
                hint="The scene tool action this shortcut runs."
                required>
            </v-select>

            <v-text-field
                v-model="template.label"
                label="Label"
                :rules="[v => !!(v && v.trim()) || 'Label is required']"
                :color="dirty ? 'dirty' : ''"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                hint="Shown in the scene tools menu."
                required>
            </v-text-field>

            <v-textarea
                v-model="template.instructions"
                label="Instructions"
                :color="dirty ? 'dirty' : ''"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                auto-grow rows="3"
                hint="Optional direction handed to the agent when the shortcut is used.">
            </v-textarea>

            <div class="mt-4" @focusout="saveTemplate">
                <IconPicker
                    v-model="template.icon"
                    :rules="[v => isValidIconName(v) || 'An mdi icon name is required']"
                    @update:model-value="dirty=true;"
                    @update:valid="iconValid = $event" />
            </div>
        </v-col>
        <v-col cols="12" sm="4" xxl="7">
            <v-checkbox
                v-model="template.favorite"
                label="Favorite"
                @update:model-value="saveTemplate"
                messages="Favorited shortcut templates will appear on the top of the list.">
            </v-checkbox>

            <v-alert v-if="orphaned" color="warning" variant="text" density="compact" icon="mdi-alert" class="mt-4">
                This template refers to an action that no longer exists in this build of Talemate.
            </v-alert>

            <v-btn
                rounded="sm"
                prepend-icon="mdi-lightning-bolt"
                color="primary"
                variant="text"
                class="mt-4"
                :disabled="!canInstall"
                @click.stop="installShortcut">
                Install shortcut
            </v-btn>
            <div v-if="!canInstall" class="text-caption text-muted">{{ installHint }}</div>
            <div v-else class="text-caption text-muted">Adds this shortcut to your scene tools menu.</div>
        </v-col>
    </v-row>
</template>

<script>
import IconPicker from './IconPicker.vue';
import { applyShortcutTemplateMessage, isValidIconName } from '@/utils/sceneToolShortcuts';

export default {
    name: 'TemplateSceneToolShortcut',
    components: {
        IconPicker,
    },
    props: {
        immutableTemplate: {
            type: Object,
            required: true
        }
    },
    data() {
        return {
            template: null,
            dirty: false,
            iconValid: false,
            sceneToolActions: [],
        };
    },
    emits: ['update'],
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'toLabel',
    ],
    computed: {
        actionItems() {
            return this.sceneToolActions.map(action => ({
                title: `${this.toLabel(action.section)} · ${action.label}`,
                value: action.id,
            }));
        },
        orphaned() {
            if (!this.template || !this.template.action_id || !this.sceneToolActions.length) {
                return false;
            }
            return !this.sceneToolActions.some(action => action.id === this.template.action_id);
        },
        complete() {
            if (!this.template || this.orphaned) {
                return false;
            }
            return !!this.template.action_id && !!(this.template.label && this.template.label.trim()) && this.iconValid;
        },
        canInstall() {
            // an uncreated template is not saved by the update emit the install
            // makes, so installing it would leave the shortcut pointing at a
            // template that never existed
            return this.complete && !!(this.template && this.template.uid);
        },
        installHint() {
            if (this.orphaned) {
                return "The shortcut's action is not available, so it cannot be installed.";
            }
            if (this.complete) {
                return 'The template has to be created before its shortcut can be installed.';
            }
            return 'An action, a label and a valid icon are required to install the shortcut.';
        },
    },
    watch: {
        immutableTemplate: {
            handler: function (val) {
                this.template = val ? {...val} : null;
            },
            immediate: true,
            deep: true
        }
    },
    methods: {
        isValidIconName,

        saveTemplate() {
            // the backend refuses a template without a usable icon, so an empty
            // or bogus one holds every field's save back — sending it would only
            // come back as a raw validation error, with the form already showing
            // itself as saved
            if (!this.iconValid) {
                this.dirty = true;
                return;
            }
            this.dirty = false;
            this.$emit('update', this.template);
        },

        installShortcut() {
            this.saveTemplate();
            this.getWebsocket().send(JSON.stringify(applyShortcutTemplateMessage(this.template)));
        },

        requestSceneToolActions() {
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'request_scene_tool_actions',
                data: {},
            }));
        },

        handleMessage(message) {
            if (message.type === 'config' && message.action === 'scene_tool_actions') {
                this.sceneToolActions = message.data.actions;
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.requestSceneToolActions();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
};
</script>
