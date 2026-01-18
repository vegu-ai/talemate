<template>
    <div :style="{ maxWidth: MAX_CONTENT_WIDTH }">
    <v-row>
        <v-col cols="12">

            <v-form>

                <v-card class="my-2" variant="text" color="muted">
                    <v-card-title class="text-white">
                        <v-icon color="primary" size="small" class="mr-2">mdi-bullhorn</v-icon>
                        Scene Direction</v-card-title>
                    <v-card-text class="text-white">
                        <v-alert color="warning" variant="outlined" density="compact" icon="mdi-flask" v-if="sceneIntent?.direction?.always_on">
                            A strong LLM (100B+), preferably with reasoning capabilities, is HIGHLY recommended for this to work in any meaningful way.
                        </v-alert>
                        <v-row dense class="mb-2">
                            <v-col cols="12" sm="6">
                                <v-checkbox
                                    v-if="sceneIntent.direction"
                                    v-model="sceneIntent.direction.always_on"
                                    label="Always On"
                                    hint="Override agent settings and always execute scene direction"
                                    persistent-hint
                                    density="compact"
                                    :color="dirty['direction_always_on'] ? 'dirty' : 'primary'"
                                    @update:model-value="setFieldDirty('direction_always_on'); updateSceneIntent()"
                                ></v-checkbox>
                            </v-col>
                            <v-col cols="12" sm="6">
                                <v-checkbox
                                    :disabled="!sceneIntent.direction.always_on"
                                    v-if="sceneIntent.direction"
                                    v-model="sceneIntent.direction.run_immediately"
                                    label="Run Immediately"
                                    hint="Execute direction immediately without yielding the first turn to the user"
                                    persistent-hint
                                    density="compact"
                                    :color="dirty['direction_run_immediately'] ? 'dirty' : 'primary'"
                                    @update:model-value="setFieldDirty('direction_run_immediately'); updateSceneIntent()"
                                ></v-checkbox>
                            </v-col>
                        </v-row>
                    </v-card-text>
                </v-card>

                

                <v-textarea
                    v-model="sceneIntent.instructions"
                    label="Director Instructions"
                    rows="4"
                    auto-grow
                    messages="Omnipresent instructions available to the director during automated scene direction and director chat."
                    :color="dirty['instructions'] ? 'dirty' : ''"
                    @update:model-value="setFieldDirty('instructions')"
                    @blur="updateSceneIntent()"
                ></v-textarea>

                <!-- overall intention -->
                <v-card-title>
                    <v-icon color="primary" size="small" class="mr-2">mdi-compass</v-icon>
                    Overall Intention
                </v-card-title>
                <v-alert color="muted" variant="text" class="text-caption">
                    The overall intention of the story. Lays out expectations for the experience, the general direction and any special rules or constraints.
                </v-alert>
                
                <ContextualGenerate 
                    ref="intentGenerate"
                    uid="wsm.scene_intent"
                    context="scene intent:overall" 
                    :original="sceneIntent.intent"
                    :templates="templates"
                    :generationOptions="generationOptions"
                    :specify-length="true"
                    @generate="content => setAndUpdateIntent(content)"
                />
                
                <v-textarea
                    v-model="sceneIntent.intent"
                    label="Overall Intention"
                    rows="4"
                    auto-grow
                    :color="dirty['intent'] ? 'dirty' : ''"
                    @update:model-value="setFieldDirty('intent')"
                    @blur="updateSceneIntent()"
                ></v-textarea>
                
                <!-- current scene phase -->
                <div v-if="hasSceneTypes">
                    <v-card-title>
                        <v-icon color="primary" size="small" class="mr-2">mdi-flag-variant</v-icon>
                        Current Phase
                    </v-card-title>
                    <v-alert color="muted" variant="text" class="text-caption">
                        <p>The current phase of the story. This will determine the type of scene that is currently
                        active. Different scene types have different rules and constraints.</p>
                        <p>
                            Regardless of type a phase also is associated with an intent. This is the specific goal or
                            objective of the scene. 
                        </p>
                    </v-alert>
                    
                    <v-row>
                        <v-col cols="12" md="6" lg="4" xl="4">
                            <v-select
                                v-model="sceneIntent.phase.scene_type"
                                :items="sceneTypes"
                                item-title="name"
                                item-value="id"
                                label="Scene Type"
                                :color="dirty['scene_type'] ? 'dirty' : ''"
                                @update:model-value="setFieldDirty('scene_type'); updateSceneIntent()"
                            ></v-select>
                        </v-col>
                    </v-row>
                    
                    <!-- Scene Type Information Display -->
                    <v-card v-if="sceneIntent.phase.scene_type" 
                           class="mb-4" variant="outlined" color="surface-variant">
                        <v-row no-gutters>
                            <!-- Description Column (Left) -->
                            <v-col cols="12" md="6" class="pa-4">
                                <v-card-subtitle>Description</v-card-subtitle>
                                <v-card-text>{{ sceneIntent.scene_types[sceneIntent.phase.scene_type].description }}</v-card-text>
                            </v-col>
                            
                            <!-- Instructions Column (Right) -->
                            <v-col cols="12" md="6" class="pa-4">
                                <v-card-subtitle>Instructions</v-card-subtitle>
                                <v-card-text class="instructions-text">{{ sceneIntent.scene_types[sceneIntent.phase.scene_type].instructions }}</v-card-text>
                            </v-col>
                        </v-row>
                    </v-card>
    
                    <ContextualGenerate 
                        v-if="sceneIntent.phase && sceneIntent.phase.scene_type"
                        ref="phaseIntentGenerate"
                        uid="wsm.scene_phase_intent"
                        :context="'scene phase intent:' + sceneIntent.phase.scene_type" 
                        :original="sceneIntent.phase.intent"
                        :templates="templates"
                        :length="256"
                        :generationOptions="generationOptions"
                        :specify-length="true"
                        @generate="content => setAndUpdatePhaseIntent(content)"
                    />
                    
                    <v-textarea v-if="sceneIntent.phase"
                        v-model="sceneIntent.phase.intent"
                        label="Current Scene Intention"
                        rows="4"
                        auto-grow
                        :length="256"
                        :color="dirty['phase_intent'] ? 'dirty' : ''"
                        @update:model-value="setFieldDirty('phase_intent')"
                        @blur="updateSceneIntent()"
                    ></v-textarea>
                </div>


                <!-- manage scene types -->
                <v-card-title>
                    <v-icon color="primary" size="small" class="mr-2">mdi-movie-open</v-icon>
                    Manage Scene Types
                </v-card-title>
                <v-alert color="muted" variant="text" class="text-caption">
                    <p>Manage the scene types that are available for the experience. Scene types are the different
                    types of scenes that can be played. Each scene type has different rules and constraints.</p>
                </v-alert>
                <v-toolbar color="mutedbg" variant="text">
                    <v-select
                        v-model="selectedSceneTypeTemplate"
                        :items="filteredSceneTypeTemplates"
                        item-title="name"
                        item-value="value"
                        label="Import from templates"
                        density="compact"
                        style="max-width: 300px;"
                        hide-details
                    ></v-select>
                    <v-btn 
                        color="primary" 
                        :disabled="!selectedSceneTypeTemplate"
                        @click="applySelectedSceneTypeTemplate()" 
                        class="ml-2"
                        prepend-icon="mdi-cube-scan"
                    >Import</v-btn>
                    <v-spacer></v-spacer>
                    <v-btn color="primary" @click="createSceneType" prepend-icon="mdi-plus">Add Scene Type</v-btn>
                </v-toolbar>
            </v-form>
            <v-table>
                <thead>
                    <tr>
                        <th class="name-column">Name</th>
                        <th class="description-column">Description</th>
                        <th class="actions-column" style="text-align: right; width: 120px;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="(sceneType, key) in this.sceneIntent.scene_types" :key="key">
                        <td class="name-column">{{ sceneType.name }}</td>
                        <td class="description-column align-start">
                            <div class="full-cell-content bg-mutedbg">{{ sceneType.description }}</div>
                        </td>
                        <td class="actions-column text-right">
                            <div class="action-buttons">
                                <v-btn color="primary" @click="editSceneType(key)" variant="text" icon density="compact">
                                    <v-icon>mdi-pencil</v-icon>
                                </v-btn>
                                <confirm-action-inline
                                    action-label="Delete"
                                    confirm-label="Delete"
                                    icon="mdi-close-circle-outline"
                                    color="delete"
                                    density="compact"
                                    @confirm="removeSceneType(key)"
                                />
                            </div>
                        </td>
                    </tr>
                </tbody>
            </v-table>
        </v-col>
    </v-row>
    </div>

    <v-dialog v-model="sceneTypeEditor" max-width="800">
        <v-card>
            <v-card-title>Scene type editor</v-card-title>
            <v-card-text>
                <v-form>
                    <v-text-field
                        v-model="sceneType.name"
                        label="Name"
                    ></v-text-field>
                    
                    <ContextualGenerate 
                        ref="sceneTypeDescriptionGenerate"
                        uid="wsm.scene_type_description"
                        :context="'scene type description:' + (sceneType.name || 'New Scene Type')" 
                        :original="sceneType.description"
                        :templates="templates"
                        :length="128"
                        :generationOptions="generationOptions"
                        :specifyLength="true"
                        @generate="content => sceneType.description = content"
                        :disabled="!sceneType.name"
                    />
                    
                    <v-textarea
                        v-model="sceneType.description"
                        label="Description"
                        auto-grow
                        max-rows="30"
                    ></v-textarea>
                    
                    <ContextualGenerate 
                        ref="sceneTypeInstructionsGenerate"
                        uid="wsm.scene_type_instructions"
                        :context="'scene type instructions:' + (sceneType.name || 'New Scene Type')" 
                        :original="sceneType.instructions"
                        :templates="templates"
                        :length="192"
                        :generationOptions="generationOptions"
                        :specifyLength="true"
                        @generate="content => sceneType.instructions = content"
                        :disabled="!sceneType.name"
                    />
                    
                    <v-textarea
                        v-model="sceneType.instructions"
                        auto-grow
                        max-rows="30"
                        label="Instructions"
                    ></v-textarea>
                </v-form>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="primary" @click="sceneTypeEditor = false">Cancel</v-btn>
                <v-btn color="primary" @click="saveSceneType">Save</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<style scoped>
.name-column {
    width: 20%;
    min-width: 120px;
}

.description-column {
    width: 65%;
}

.instructions-text {
    white-space: pre-line;
}

.actions-column {
    width: 120px;
    min-width: 120px;
    vertical-align: top;
}

.action-buttons {
    display: flex;
    flex-direction: row;
    justify-content: flex-end;
    align-items: center;
    gap: 4px;
    margin-top: 4px;
}

.full-cell-content {
    white-space: pre-line;
    padding: 8px 4px;
    max-height: none;
    border-radius: 4px;
    font-size: 0.9rem;
    overflow-wrap: break-word;
}

.v-table {
    table-layout: fixed;
}

/* Keep the tooltip content styling for potential future use */
.tooltip-content {
    white-space: pre-line;
    max-width: 400px;
    max-height: 300px;
    overflow-y: auto;
    padding: 10px;
}
</style>

<script>
import ConfirmActionInline from './ConfirmActionInline.vue';
import ContextualGenerate from './ContextualGenerate.vue';
import { MAX_CONTENT_WIDTH } from '@/constants';

const BLANK_SCENE_TYPE = {
    name: '',
    description: '',
    instructions: '',
}

export default {
    name: 'WorldStateManagerSceneDirection',
    components: {
        ConfirmActionInline,
        ContextualGenerate
    },
    props: {
        immutableScene: Object,
        isVisible: Boolean,
        templates: Object,
        generationOptions: {
            type: Object,
            required: false,
            default: () => ({})
        },
    },
    inject:[
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'setWaitingForInput',
        'requestSceneAssets',
    ],
    computed: {
        hasSceneTypes() {
            return this.sceneIntent && this.sceneIntent.scene_types && Object.keys(this.sceneIntent.scene_types).length > 0;
        },
        sceneTypes() {
            return Object.values(this.sceneIntent.scene_types);
        },
        filteredSceneTypeTemplates() {
            // Check if we have templates from props
            if (!this.templates || !this.templates.by_type || !this.templates.by_type.scene_type) {
                return [];
            }
            
            // Get existing scene type names in lowercase for comparison
            const existingSceneTypeNames = Object.values(this.sceneIntent.scene_types)
                .map(sceneType => sceneType.name.toLowerCase());
            
            // Filter templates to only show scene_type templates that are not already in use
            // Make sure we can select them in the dropdown
            return Object.values(this.templates.by_type.scene_type)
                .filter(template => !existingSceneTypeNames.includes(template.name.toLowerCase()))
                .map(template => ({
                    name: template.name,
                    value: template.uid,
                    description: template.description,
                    instructions: template.instructions,
                    group: template.group,
                    uid: template.uid
                }));
        }
    },
    watch: {
        isVisible: {
            immediate: true,
            handler(value) {
                if(value) {
                    this.getSceneIntent();
                }
            }
        },
        templates: {
            immediate: true,
            handler(value) {
                console.log("Templates", JSON.stringify(value, null, 2));
            }
        }
    },
    data() {
        return {
            MAX_CONTENT_WIDTH,
            sceneIntent: {
                scene_types: {},
                intent: '',
                instructions: '',
                direction: {
                    always_on: false,
                    run_immediately: false,
                },
                phase: {
                    scene_type: '',
                    intent: '',
                }
            },
            newSceneTypeName: '',
            sceneTypeEditor: false,
            newSceneType: { ...BLANK_SCENE_TYPE },
            sceneType: { ...BLANK_SCENE_TYPE },
            dirty: {},
            deleteColumnWidth: 200,
            selectedSceneTypeTemplate: null,
        }
    },
    methods: {
        setFieldDirty(name) {
            this.dirty[name] = true;
        },

        clearDirty() {
            this.dirty = {};
        },

        setAndUpdateIntent(content) {
            this.sceneIntent.intent = content;
            this.setFieldDirty('intent');
            this.updateSceneIntent();
        },
        
        setAndUpdatePhaseIntent(content) {
            this.sceneIntent.phase.intent = content;
            this.setFieldDirty('phase_intent');
            this.updateSceneIntent();
        },

        createSceneType() {
            this.sceneType = { ...BLANK_SCENE_TYPE };
            this.sceneTypeEditor = true;
        },

        saveSceneType() {
            // if id is undefined, make it from name, making sure
            // to lowercase and replace spaces with underscores
            if(!this.sceneType.id) {
                this.sceneType.id = this.sceneType.name.toLowerCase().replace(/\s/g, '_');
            }

            this.sceneIntent.scene_types[this.sceneType.id] = this.sceneType;
            this.sceneType = { ...BLANK_SCENE_TYPE };
            this.sceneTypeEditor = false;

            // if no phase is set currently, set it to the first scene type
            if(!this.sceneIntent.phase.scene_type) {
                this.sceneIntent.phase.scene_type = Object.keys(this.sceneIntent.scene_types)[0];
            }
            
            // Update the scene intent after saving a scene type
            this.updateSceneIntent();
        },

        editSceneType(sceneTypeId) {
            this.sceneType = { ...this.sceneIntent.scene_types[sceneTypeId] };
            this.sceneTypeEditor = true;
        },

        getSceneIntent() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_scene_intent',
            }));
        },

        updateSceneIntent() {
            if(!this.sceneIntent) {
                return;
            }

            console.log('Updating scene intent', this.sceneIntent);

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_scene_intent',
                ...this.sceneIntent,
            }));
        },

        removeSceneType(key) {
            if(!this.sceneIntent || !this.sceneIntent.scene_types) {
                return;
            }

            // Check if we're deleting the currently selected scene type
            // Consider that phase might be null
            const isCurrentType = this.sceneIntent.phase && this.sceneIntent.phase.scene_type === key;
            
            delete this.sceneIntent.scene_types[key];
            
            // If we deleted the current scene type, update the selection
            if (isCurrentType) {
                const remainingTypes = Object.keys(this.sceneIntent.scene_types);
                if (remainingTypes.length > 0) {
                    // Select the first available scene type
                    this.sceneIntent.phase.scene_type = remainingTypes[0];
                } else {
                    // No scene types left, clear the selection
                    this.sceneIntent.phase.scene_type = '';
                }
            }
            
            // Update the scene intent after removing a scene type
            this.updateSceneIntent();
        },

        handleMessage(message) {
            // If another part of the system updates scene intent, keep this view in sync
            // (but don't clobber local edits).
            if (message.type === 'scene_intent' && message.action === 'updated') {
                const hasDirty = Object.values(this.dirty || {}).some(Boolean);
                if (!hasDirty) {
                    this.sceneIntent = message.data;
                }
                return;
            }

            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action === 'get_scene_intent') {
                console.log(message);
                this.sceneIntent = message.data;
                this.clearDirty();
            } else if (message.action === 'set_scene_intent') {
                // Clear dirty flags when server confirms update
                this.clearDirty();
            }
        },

        applySelectedSceneTypeTemplate() {
            if (!this.selectedSceneTypeTemplate) {
                return;
            }

            const template = this.filteredSceneTypeTemplates.find(t => t.value === this.selectedSceneTypeTemplate);
            if (template) {
                this.applySceneTypeTemplate(template);
                this.selectedSceneTypeTemplate = null; // Reset selection after applying
            }
        },
        
        applySceneTypeTemplate(template) {
            // Create a scene type ID from the name
            const sceneTypeId = template.name.toLowerCase().replace(/\s/g, '_');
            
            // Create the scene type object
            const sceneType = {
                id: sceneTypeId,
                name: template.name,
                description: template.description,
                instructions: template.instructions
            };
            
            // Add to scene intent
            this.sceneIntent.scene_types[sceneTypeId] = sceneType;
            
            // Update the scene intent
            this.updateSceneIntent();
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.$nextTick(() => {
            this.getSceneIntent();
        });
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}

</script>