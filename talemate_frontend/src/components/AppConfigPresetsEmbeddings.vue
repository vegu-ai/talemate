<template>

    <v-row>
        <v-col cols="4">
            <!-- list with all presets by key, read from `config` -->
            <v-list slim selectable v-model:selected="selected" color="primary" :disabled="busy">

                <!-- add new -->
                <v-list-item @click.stop="addNewPreset" prepend-icon="mdi-plus" :value="'$NEW'">
                    <v-list-item-title>Add new</v-list-item-title>
                </v-list-item>

                <!-- existing -->
                <v-list-item v-for="(preset, preset_key) in config.embeddings" :key="preset_key" :value="preset_key" prepend-icon="mdi-tune">
                    <v-list-item-title>{{ preset.model }}</v-list-item-title>
                    <v-list-item-subtitle>{{ preset.embeddings }}</v-list-item-subtitle>
                </v-list-item>
            </v-list>
        </v-col>
        <v-col cols="8">
            <!--
            class EmbeddingFunctionPreset(BaseModel):
                embeddings: str = "sentence-transformer"
                model: str = "all-MiniLM-L6-v2"
                trust_remote_code: bool = False
                device: str = "cpu"
                distance: float = 1.5
                distance_mod: int = 1
                distance_function: str = "l2"
                fast: bool = True
                gpu_recommendation: bool = False
                local: bool = True

            Display editable form for the selected preset

            Will use sliders for float and int values, and checkboxes for bool values
            -->
            <div v-if="newPreset !== null">
                <v-card class="overflow-y-auto">
                    <v-form ref="formNewPreset" v-model="formNewPresetValid">
                        <v-card-title>
                            Add new embeddings preset
                        </v-card-title>
                        <v-card-text>
                            <v-select v-model="newPreset.embeddings" :items="embeddings" label="Embeddings" :rules="[rulesNewPreset.required]"></v-select>
                            
                            <v-text-field v-model="newPreset.model" label="Model"  :rules="[rulesNewPreset.required, rulesNewPreset.exists]"></v-text-field>
                        </v-card-text>
                    </v-form>

                    <v-card-actions>
                        <v-btn color="primary" @click="commitNewPreset" prepend-icon="mdi-check-circle-outline">Continue</v-btn>
                        <v-btn color="error" @click="newPreset = null; selected=[]" prepend-icon="mdi-close">Cancel</v-btn>
                    </v-card-actions>
                </v-card>

            </div>

            <div v-else-if="selected.length === 1">
                <v-form class="overflow-y-auto">
                    <v-card class="overflow-y-auto">
                        <v-card-title>
                            <v-row no-gutters>
                                <v-col cols="8">
                                    {{ toLabel(selected[0]) }}
                                </v-col>
                                <v-col cols="4" class="text-right" v-if="config.embeddings[selected[0]].custom === false">
                                    <v-btn variant="text" size="small" color="warning" prepend-icon="mdi-refresh" @click="config.embeddings[selected[0]] = {...immutableConfig.presets.embeddings_defaults[selected[0]]}">Reset</v-btn>
                                </v-col>
                                <v-col cols="4" class="text-right" v-else>
                                    <v-btn variant="text" size="small" color="delete" prepend-icon="mdi-close-box-outline" @click="deleteCustomPreset(selected[0])">Delete</v-btn>
                                </v-col>
                            </v-row>
                        </v-card-title>

                        <v-card-text>
                            <v-select disabled v-model="config.embeddings[selected[0]].embeddings" :items="embeddings" label="Embeddings" @update:model-value="setPresetChanged(selected[0])"></v-select>
                            
                            <v-text-field disabled v-model="config.embeddings[selected[0]].model" label="Model" @update:model-value="setPresetChanged(selected[0])"></v-text-field>

                            <v-checkbox :disabled="busy" v-if="isSentenceTransformer" v-model="config.embeddings[selected[0]].trust_remote_code" hide-details label="Trust Remote Code" @update:model-value="setPresetChanged(selected[0])"></v-checkbox>

                            <!-- trust remote code can be dangerous, if it is enabled display a v-alert message about the implications -->
                            <v-alert :disabled="busy" class="mb-4" density="compact" v-if="config.embeddings[selected[0]].trust_remote_code" color="warning" icon="mdi-alert" variant="text">Trusting remote code can be dangerous, only enable if you trust the source</v-alert>

                            <v-select :disabled="busy" v-if="isLocal" v-model="config.embeddings[selected[0]].device" :items="devices" label="Device" @update:model-value="setPresetChanged(selected[0])"></v-select>

                            <v-slider :disabled="busy" thumb-label="always" density="compact" v-model="config.embeddings[selected[0]].distance" min="0.1" max="10.0" step="0.1" label="Distance" @update:model-value="setPresetChanged(selected[0])"></v-slider>

                            <v-slider :disabled="busy" thumb-label="always" density="compact" v-model="config.embeddings[selected[0]].distance_mod" min="1" max="1000" step="10" label="Distance Mod" @update:model-value="setPresetChanged(selected[0])"></v-slider>

                            <v-select :disabled="busy" v-model="config.embeddings[selected[0]].distance_function" :items="distanceFunctions" label="Distance Function" @update:model-value="setPresetChanged(selected[0])"></v-select>


                            <v-row>
                                <v-col cols="3">
                                    <v-checkbox :disabled="busy" v-model="config.embeddings[selected[0]].fast" label="Fast" @update:model-value="setPresetChanged(selected[0])"></v-checkbox>
                                </v-col>
                                <v-col cols="6">
                                    <v-checkbox :disabled="busy" v-if="isLocal" v-model="config.embeddings[selected[0]].gpu_recommendation" label="GPU Recommendation" @update:model-value="setPresetChanged(selected[0])"></v-checkbox>
                                </v-col>
                                <v-col cols="3">
                                    <v-checkbox :disabled="busy" v-model="config.embeddings[selected[0]].local" label="Local" @update:model-value="setPresetChanged(selected[0])"></v-checkbox>
                                </v-col>
                            </v-row>

                            <v-alert v-if="isCurrentyLoaded" color="unsaved" icon="mdi-refresh" density="compact" variant="text">This embedding is currently loaded by the Memory agent and saving changes will cause the associated databse to be recreated and repopulated immediately after saving. Depending on the size of the model and scene this may take a while.</v-alert>

                            <p v-if="busy">
                                <v-progress-linear color="primary" height="2" indeterminate></v-progress-linear>
                            </p>
                        </v-card-text>
                    </v-card>
                </v-form>
            </div>
            <div v-else>
                <v-alert color="grey" variant="text">Select a preset to edit</v-alert>
            </div>
        </v-col>
    </v-row>

</template>
<script>

export default {
    name: 'AppConfigPresets',
    components: {
    },
    props: {
        immutableConfig: Object,
        memoryAgentStatus: Object,
        sceneActive: Boolean,
    },
    watch: {
        immutableConfig: {
            handler: function(newVal) {
                console.log('immutableConfig changed', newVal);
                if(!newVal) {
                    this.config = {};
                    return;
                }

                this.config = {...newVal.presets};
            },
            immediate: true,
            deep: true,
        },
        busy: {
            handler: function(newVal) {
                if(newVal) {
                    this.$emit('busy');
                } else {
                    this.$emit('done');
                }
            },
            immediate: true,
        }
    },
    emits: [
        'update',
        'busy',
        'done',
    ],
    computed: {
        isLocal() {

            if(this.selected.length === 0) {
                return false;
            }

            return this.config.embeddings[this.selected[0]].local;
        },
        isSentenceTransformer() {
            if(this.selected.length === 0) {
                return false;
            }

            return this.config.embeddings[this.selected[0]].embeddings === 'sentence-transformer';
        },
        isCurrentyLoaded() {
            console.log('isCurrentyLoaded', this.memoryAgentStatus, this.selected, this.sceneActive);
            if(!this.memoryAgentStatus || !this.selected.length || !this.sceneActive) {
                return false;
            }

            return this.memoryAgentStatus.details.model.value == this.config.embeddings[this.selected[0]].model;
        },
        busy() {
            return this.memoryAgentStatus && this.memoryAgentStatus.status === 'busy';
        }
    },
    data() {
        return {
            selected: [],
            newPreset: null,
            rulesNewPreset: {
                required: value => !!value || 'Required.',
                exists: value => !this.config.embeddings[value] || 'Already exists.',
            },
            formNewPresetValid: false,
            config: {
                embeddings: {},
            },
            embeddings: [
                {title: 'SentenceTransformer', value: 'sentence-transformer'},
                {title: 'Instructor', value: 'instructor'},
                {title: 'OpenAI', value: 'openai'},
            ],
            distanceFunctions: [
                {title: 'Cosine similarity', value: 'cosine'},
                {title: 'Inner product', value: 'ip'},
                {title: 'Squared L2', value: 'l2'},
            ],
            devices: [
                {title: 'CPU', value: 'cpu'},
                {title: 'CUDA', value: 'cuda'},
            ],
        }
    },
    methods: {

        setPresetChanged(presetName) {
            // this ensures that the change gets saved
            this.config.embeddings[presetName].changed = true;
        },

        deleteCustomPreset(presetName) {
            this.selected = [];
            delete this.config.embeddings[presetName];
        },

        addNewPreset() {
            this.newPreset = {
                embeddings: 'sentence-transformer',
                model: '',
                custom: true,
                trust_remote_code: false,
                device: 'cpu',
                distance: 1.5,
                distance_mod: 1,
                distance_function: 'l2',
                fast: true,
                gpu_recommendation: false,
                local: true,
                changed: true,
            }
        },

        commitNewPreset() {

            this.$refs.formNewPreset.validate();

            if(!this.formNewPresetValid) {
                return;
            }

            this.config.embeddings[this.newPreset.model] = this.newPreset;
            this.selected = [this.newPreset.model];
            this.newPreset = null;
        },

        toLabel(key) {
            return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        },
    },
}

</script>