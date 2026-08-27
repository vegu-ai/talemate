<template>
    <v-card v-if="client" elevation="0" density="compact">
        <v-card-title class="text-subtitle-2 d-flex align-center">
            <v-icon color="highlight1" size="small" class="mr-1">mdi-tune</v-icon>
            <span class="flex-grow-1 text-truncate">{{ client.name }}</span>
            <v-tooltip text="Unpin these parameters">
                <template v-slot:activator="{ props }">
                    <v-btn v-bind="props" size="x-small" variant="text" density="comfortable" icon="mdi-pin-off" @click="$emit('unpin')"></v-btn>
                </template>
            </v-tooltip>
        </v-card-title>

        <v-card-subtitle class="text-caption pb-2">
            <span v-if="groupKey">Inference group {{ groupKey }}</span>
            <span v-else>No inference group</span>
        </v-card-subtitle>

        <!-- a card subtitle is a single clipped line, so this hint is a plain
             block with the card's own horizontal padding -->
        <div v-if="groupKey" class="text-caption text-medium-emphasis px-4 pb-2">
            Client support varies by parameter — a parameter this client does not support is stored with the group but never sent.
        </div>

        <v-card-text v-if="!groupKey">
            <v-alert density="compact" variant="text" type="info" class="text-caption">
                This client uses the Default parameters, which every client without a group shares. Name a group to tune the parameters for this client alone.
            </v-alert>
            <v-text-field
                v-model="newGroupName"
                density="compact"
                variant="underlined"
                label="New group name"
                :error-messages="newGroupError ? [newGroupError] : []"
                append-inner-icon="mdi-plus-box"
                @keydown.enter="createGroup"
                @click:append-inner="createGroup"
                messages="[Enter] to create the group. The Default parameters are copied into it."
            ></v-text-field>
        </v-card-text>

        <v-card-text v-else-if="!draft">
            <v-alert density="compact" variant="text" type="warning" class="text-caption">
                The group {{ groupKey }} is gone. Pick another one from the client's preset menu.
            </v-alert>
        </v-card-text>

        <v-card-text v-else>
            <v-select
                v-model="presetKey"
                :items="presetItems"
                label="Preset"
                density="compact"
                variant="underlined"
                hide-details
                class="mb-4"
            ></v-select>

            <InferenceParamsForm narrow collapsible-advanced :preset="draft" @change="scheduleSave" />

            <v-btn variant="text" size="x-small" color="primary" prepend-icon="mdi-cog" @click="openInSettings">Open in settings</v-btn>
        </v-card-text>
    </v-card>
</template>

<script>

import InferenceParamsForm from './InferenceParamsForm.vue';
import { SAVE_DELAY_MS } from '@/utils/clientSaveState';
import { hasOwnName } from '@/utils/nameKeyedMap';
import {
    changedValues,
    createPresetGroupForClient,
    deepCopy,
    groupNameError,
    presetKeys,
    presetLabel,
    presetsScope,
    writePresetParams,
} from '@/utils/inferencePresets';

export default {
    name: 'ClientInferenceParamsPanel',
    components: {
        InferenceParamsForm,
    },
    props: {
        immutableConfig: Object,
        clientName: String,
    },
    inject: [
        'saveAppConfig',
        'openAppConfig',
        'notifyError',
    ],
    emits: [
        'unpin',
    ],
    data() {
        return {
            presetKey: null,
            // the edited copy of the preset — the stored config only catches up
            // on the broadcast that follows a save
            draft: null,
            newGroupName: '',
            newGroupError: null,
        }
    },
    computed: {
        client() {
            // a client name can be any string, `toString` included — an
            // inherited member would resolve to a function here
            if (!hasOwnName(this.immutableConfig?.clients, this.clientName)) {
                return null;
            }
            return this.immutableConfig.clients[this.clientName];
        },
        groupKey() {
            return this.client?.preset_group || '';
        },
        presetItems() {
            return presetKeys(this.immutableConfig?.presets, this.groupKey).map(key => ({
                title: presetLabel(key),
                value: key,
            }));
        },
    },
    watch: {
        // the whole object is replaced on every app_config push, so a shallow
        // watcher catches every change
        immutableConfig: {
            handler() {
                this.syncDraft();
            },
            immediate: true,
        },
        clientName() {
            this.flushSave();
            this.presetKey = null;
            this.newGroupName = '';
            this.newGroupError = null;
            this.syncDraft(true);
        },
        presetKey() {
            this.flushSave();
            this.syncDraft(true);
        },
        newGroupName() {
            this.newGroupError = null;
        },
    },
    methods: {
        storedPreset() {
            const scope = presetsScope(this.immutableConfig?.presets, this.groupKey);
            if (!scope) {
                return null;
            }
            if (!this.presetKey || !scope[this.presetKey]) {
                const keys = Object.keys(scope);
                this.presetKey = keys.includes('conversation') ? 'conversation' : keys[0] || null;
            }
            return this.presetKey ? scope[this.presetKey] || null : null;
        },
        // Takes the stored values over, unless edits of ours are still on their
        // way to the backend — those would be overwritten by the config the
        // save has not reached yet.
        syncDraft(force = false) {
            const stored = this.storedPreset();
            if (!stored) {
                // there is nothing left to write into, and a save left pending
                // here would stop every later broadcast from rebuilding the
                // draft
                this.cancelPendingSave();
                this.draft = null;
                this.baseline = null;
                return;
            }
            if (this.pendingSave && !force) {
                return;
            }
            this.draft = deepCopy(stored);
            this.baseline = deepCopy(stored);
        },
        cancelPendingSave() {
            clearTimeout(this.saveTimeout);
            this.saveTimeout = null;
            this.pendingSave = false;
            this.pendingTarget = null;
        },
        scheduleSave() {
            // the target is taken now, not when the timer fires: switching
            // preset or client in between flushes these edits to where they
            // were made
            this.pendingTarget = { groupKey: this.groupKey, presetKey: this.presetKey };
            this.pendingSave = true;
            clearTimeout(this.saveTimeout);
            this.saveTimeout = setTimeout(() => this.flushSave(), SAVE_DELAY_MS);
        },
        flushSave() {
            clearTimeout(this.saveTimeout);
            this.saveTimeout = null;
            const target = this.pendingTarget;
            this.pendingTarget = null;
            const values = changedValues(this.draft, this.baseline);
            if (!target || !Object.keys(values).length) {
                this.pendingSave = false;
                return;
            }
            this.baseline = deepCopy(this.draft);
            // only the mutation sees the payload this lands on: a group deleted
            // by a save still in flight is not in the config we last received
            let written = true;
            this.saveAppConfig((config) => {
                written = writePresetParams(config.presets, { ...target, values });
                return written;
            }, {
                label: 'inference presets',
                onComplete: () => { this.pendingSave = false; },
                onError: () => {
                    this.pendingSave = false;
                    this.syncDraft(true);
                },
            });
            if (!written) {
                this.pendingSave = false;
                this.notifyError(`${presetLabel(target.presetKey)} is no longer part of that group — the change was not saved.`);
                this.syncDraft(true);
            }
        },
        createGroup() {
            this.newGroupError = groupNameError(this.immutableConfig?.presets, this.newGroupName);
            if (this.newGroupError) {
                return;
            }
            const clientName = this.clientName;
            const groupName = this.newGroupName;
            let created = null;
            this.saveAppConfig((config) => {
                created = createPresetGroupForClient(config, { clientName, groupName });
                return created !== null;
            }, { label: 'inference presets' });
            if (!created) {
                this.newGroupError = 'That group already exists';
                return;
            }
            this.newGroupName = '';
        },
        openInSettings() {
            this.openAppConfig('presets', 'inference', this.groupKey);
        },
    },
    created() {
        // deliberately not in data(): the timer, the in-flight flag and the
        // values the draft started from need no reactivity
        this.saveTimeout = null;
        this.pendingSave = false;
        this.pendingTarget = null;
        this.baseline = null;
    },
    beforeUnmount() {
        this.flushSave();
    },
}

</script>
