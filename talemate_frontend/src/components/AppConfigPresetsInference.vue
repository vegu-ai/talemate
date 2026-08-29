<template>

    <v-alert density="compact" type="warning" variant="text">
        <p>
            This interface is a work in progress and provides basic parameter preset editing.
        </p>
        <p class="text-body-small text-medium-emphasis">
            Client support varies by parameter. <span class="text-primary">All presets are active</span> based on agent actions. Default values recommended unless you understand the parameters.
        </p>
    </v-alert>

    <v-card elevation="0" density="compact">
        <v-card-text>
            <v-row>
                <v-col cols="4">
                    <v-select v-model="group" :items="groupItems" label="Group" variant="underlined">
                        <template v-slot:append-inner>
                            <v-icon color="delete" v-if="group !== ''" @click="$refs.confirmDeleteGroup.initiateAction({group: group})">mdi-close-circle-outline</v-icon>
                        </template>
                    </v-select>
                </v-col>
                <v-col cols="8" class="text-right">
                    <v-text-field v-model="newGroupName" @keydown.enter="createGroup" label="New Group Name" variant="underlined" messages="[Enter] to create a new group. Parameters will be copied from current group.">
                    </v-text-field>
                </v-col>

            </v-row>
        </v-card-text>
    </v-card> 



    <v-row>
        <v-col cols="4">
            <!-- list with all presets by key, read from `config` -->
            <v-list slim selectable v-model:selected="selected" color="primary">
                <v-list-item v-for="(preset, preset_key) in config.inference" :key="preset_key" :value="preset_key" prepend-icon="mdi-tune">
                    <v-list-item-title>{{ toLabel(preset_key) }}</v-list-item-title>
                </v-list-item>
            </v-list>
        </v-col>
        <v-col cols="8">
            <div v-if="selected.length === 1">
                <v-form>
                    <v-card>
                        <v-card-title>
                            <v-row no-gutters>
                                <v-col cols="6">
                                    {{ toLabel(selected[0]) }}
                                </v-col>
                                <v-col cols="6" class="text-right">
                                    <v-btn variant="text" size="small" color="primary" prepend-icon="mdi-content-copy" @click="$refs.confirmApplyToAll.initiateAction({preset: toLabel(selected[0])})">Apply to all</v-btn>
                                    <v-btn variant="text" size="small" color="warning" prepend-icon="mdi-refresh" @click="$refs.confirmReset.initiateAction({preset: toLabel(selected[0])})">Reset</v-btn>
                                </v-col>
                            </v-row>
                        </v-card-title>

                        <v-card-text overflow-y-visible>
                            <InferenceParamsForm :preset="selectedPreset" @change="setPresetChanged()" />
                        </v-card-text>
                    </v-card>
                </v-form>
            </div>
            <div v-else>
                <v-alert class="text-medium-emphasis" variant="text">Select a preset to edit</v-alert>
            </div>
        </v-col>
    </v-row>

    <ConfirmActionPrompt ref="confirmApplyToAll" @confirm="applyToAll" actionLabel="Apply to all presets" icon="mdi-content-copy" color="primary" confirmText="Apply" cancelText="Cancel" :maxWidth="400" description="Apply the parameter values of {preset} to all other presets in this group? This will overwrite their current values." />

    <ConfirmActionPrompt ref="confirmReset" @confirm="reset" actionLabel="Reset preset" icon="mdi-refresh" color="warning" confirmText="Reset" cancelText="Cancel" :maxWidth="400" description="Reset {preset} to its default values?" />

    <ConfirmActionPrompt ref="confirmDeleteGroup" @confirm="deleteGroup" actionLabel="Delete group" icon="mdi-close-circle-outline" confirmText="Delete" cancelText="Cancel" :maxWidth="400" description="Are you sure you want to delete the {group} group?" />

</template>
<script>

import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import InferenceParamsForm from './InferenceParamsForm.vue';
import { hasOwnName } from '@/utils/nameKeyedMap';
import {
    addPresetGroup,
    deepCopy,
    presetGroupItems,
    presetLabel,
    presetsScope,
} from '@/utils/inferencePresets';

export default {
    name: 'AppConfigPresets',
    components: {
        ConfirmActionPrompt,
        InferenceParamsForm,
    },
    props: {
        immutableConfig: Object,
    },
    computed: {
        groupItems() {
            return presetGroupItems(this.config);
        },
        scope() {
            return presetsScope(this.config, this.group);
        },
        selectedPreset() {
            return this.scope?.[this.selected[0]];
        },
    },
    watch: {
        immutableConfig: {
            handler: function(newVal) {
                if(!newVal) {
                    this.config = {};
                    return;
                }

                this.config = {...newVal.presets};
            },
            immediate: true,
            deep: true,
        },
    },
    emits: [
        'update',
    ],
    data() {
        return {
            selected: [],
            config: {
                inference: {},
            },
            group: '',
            newGroupName: '',
        }
    },
    methods: {
        setSelection(group){
            // ensure group is valid
            if(!hasOwnName(this.config.inference_groups, group)) {
                return;
            }
            this.group = group;
        },
        deleteGroup() {
            delete this.config.inference_groups[this.group];
            this.group = '';
        },

        reset() {
            this.scope[this.selected[0]] = deepCopy(this.immutableConfig.presets.inference_defaults[this.selected[0]])
        },

        applyToAll() {
            const presets = this.scope;
            const source = deepCopy(presets[this.selected[0]]);
            for(const key in presets) {
                if(key === this.selected[0]) {
                    continue;
                }
                presets[key] = {...deepCopy(source), changed: true};
            }
        },

        createGroup() {
            const created = addPresetGroup(this.config, {
                groupName: this.newGroupName,
                sourceGroupKey: this.group,
            });
            if(!created) {
                return;
            }

            this.group = created;
            this.newGroupName = '';
        },

        setPresetChanged() {
            this.selectedPreset.changed = true;
        },

        toLabel(key) {
            return presetLabel(key);
        },
    },
}

</script>
