<template>
    <div :style="{ maxWidth: MAX_CONTENT_WIDTH }">
        <v-row>
            <v-col cols="12">
                <v-card>
                    <v-alert density="compact" variant="outlined" color="grey-darken-2" class="ma-4">
                        <template v-slot:prepend>
                            <v-icon color="primary">mdi-earth</v-icon>
                        </template>
                        <div class="text-muted">
                            Share specific characters, world entries and history across connected <span class="font-weight-bold text-primary">{{ scene.data.project_name }}</span> scenes.
                        </div>
                    </v-alert>

                    <v-card class="ma-4" elevation="3" variant="tonal" color="grey-darken-3">
                        <v-card-text class="text-muted" >
                            <div v-if="selectedItem">
                                This scene is linked to the <span class="font-weight-bold text-primary">{{ selectedItem.filename }}</span> shared context.

                                <v-chip class="mr-2" label color="highlight6" prepend-icon="mdi-account">{{ sharedCharactersCount }} shared characters</v-chip>
                                <v-chip class="mr-2" label color="highlight6" prepend-icon="mdi-text-box-search">{{ sharedWorldEntriesCount }} shared world entries</v-chip>

                                <v-btn color="primary" variant="text" prepend-icon="mdi-script-text" @click="openNewSceneDialog">
                                    <v-tooltip activator="parent">Create a new scene with the same shared context.</v-tooltip>
                                    New scene
                                </v-btn>
                            </div>
                            <div v-else>
                                No shared context linked. <span v-if="items.length">You can link one by selecting a shared context file from the list below.</span><span v-else><v-btn color="primary" variant="text" prepend-icon="mdi-plus" @click="openCreateDialog">Create shared context</v-btn></span>
                            </div>
                        </v-card-text>
                    </v-card>

                    <v-card-text>
                        <v-list
                            color="primary"
                            density="compact"
                        >
                            <v-list-subheader color="grey">Available</v-list-subheader>
                            <v-list-item
                                v-for="item in items"
                                :key="item.filepath"
                                :ripple="false"
                                lines="one"
                                class="align-center"
                            >
                                <template v-slot:prepend>
                                    <v-checkbox
                                        :model-value="isSelected(item)"
                                        @update:model-value="(v) => toggle(item, v)"
                                        :label="item.filename"
                                        color="primary"
                                        density="compact"
                                        hide-details
                                        class="my-0"
                                    />
                                </template>
                                <template v-slot:append>
                                    <ConfirmActionInline
                                        :disabled="false"
                                        action-label="Delete"
                                        confirm-label="Confirm delete"
                                        @confirm="() => remove(item)"
                                    />
                                </template>
                            </v-list-item>
                            <v-list-item v-if="!items.length" disabled>
                                <v-list-item-title class="text-grey">No shared context files found</v-list-item-title>
                            </v-list-item>
                        </v-list>
                    </v-card-text>
                    <v-card-actions>
                        <v-btn color="primary" prepend-icon="mdi-refresh" @click="refresh">Refresh</v-btn>
                        <v-spacer></v-spacer>
                        <v-btn color="primary" prepend-icon="mdi-plus" @click="openCreateDialog">New</v-btn>
                    </v-card-actions>
                </v-card>
            </v-col>
        </v-row>
    </div>

    <v-dialog v-model="createDialog" width="480">
            <v-card>
                <v-card-title>
                    <v-icon size="small" class="mr-2">mdi-book-plus</v-icon>
                    Create Shared Context
                </v-card-title>
                <v-card-text>
                    <v-text-field v-model="newName" label="Filename" hint="Will be stored as .json inside the scene's shared-context folder" />
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn variant="tonal" @click="cancelCreate">Cancel</v-btn>
                    <v-btn color="primary" @click="create">Create</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- New Scene (with premise and shared character selection) -->
        <v-dialog v-model="newSceneDialog" width="640">
            <v-card>
                <v-card-title>
                    <v-icon size="small" class="mr-2">mdi-script-text</v-icon>
                    Create New Scene in shared context
                </v-card-title>
                <v-card-text>
                    <v-alert v-if="!scene?.data?.saved && !creatingNewScene" color="muted" variant="text" density="compact" class="mb-4">
                        <template v-slot:prepend>
                            <v-icon color="warning">mdi-alert-circle-outline</v-icon>
                        </template>
                        <div class="text-muted">
                            The scene currently open is not saved. Any changes that aren't saved will not be included in the new scene and <strong>will be lost</strong>.
                        </div>
                    </v-alert>
                    <v-alert density="compact" variant="outlined" color="grey-darken-2" class="mb-4">
                        <template v-slot:prepend>
                            <v-icon color="primary">mdi-earth</v-icon>
                        </template>
                        <div class="text-muted">
                            The new scene will be linked to the <span class="font-weight-bold text-primary">{{ selectedItem.filename }}</span> shared context.
                        </div>
                    </v-alert>


                    <v-textarea
                        v-model="newScenePremise"
                        rows="4"
                        auto-grow
                        max-rows="12"
                        label="Instructions for new premise. (optional)"
                        hint="Short instructions for what kind of introduction to generate for the new scene."
                    />

                    <div class="mt-4">
                        <div v-if="availableSharedCharacters.length">
                            <v-combobox
                                v-model="selectedSharedCharacters"
                                :items="availableSharedCharacters"
                                label="Select characters to activate"
                                color="primary"
                                multiple
                                chips
                                closable-chips
                                hide-details
                                variant="solo"
                                class="mt-2"
                            />
                        </div>
                        <v-card v-else elevation="0" color="grey-darken-3" variant="tonal" class="mt-2">
                            <v-card-text class="text-grey">There are no shared characters in the shared context.</v-card-text>
                        </v-card>
                    </div>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn color="cancel" prepend-icon="mdi-cancel" :disabled="creatingNewScene"  @click="newSceneDialog=false">Cancel</v-btn>
                    <v-btn color="primary" prepend-icon="mdi-script-text" :disabled="creatingNewScene" :loading="creatingNewScene" @click="confirmCreateNewScene">Create and load</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
</template>

<script>
import ConfirmActionInline from './ConfirmActionInline.vue';
import { MAX_CONTENT_WIDTH } from '@/constants';
export default {
    name: 'WorldStateManagerSceneSharedContext',
    props: {
        scene: Object,
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    components: {
        ConfirmActionInline,
    },
    data() {
        return {
            MAX_CONTENT_WIDTH,
            items: [],
            selected: null,
            createDialog: false,
            newName: '',
            sharedCounts: { characters: 0, world_entries: 0 },
            // New scene dialog state
            newSceneDialog: false,
            newScenePremise: '',
            availableSharedCharacters: [],
            selectedSharedCharacters: [],
            creatingNewScene: false,
        }
    },
    methods: {
        refresh() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'list_shared_contexts',
            }));
        },
        openNewSceneDialog() {
            // reset state
            this.newScenePremise = ''
            this.selectedSharedCharacters = []
            this.availableSharedCharacters = []
            this.creatingNewScene = false
            this.newSceneDialog = true

            // request character list to filter shared
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_list',
            }));
        },
        openCreateDialog() {
            this.newName = ''
            this.createDialog = true
        },
        isSelected(item) {
            const fp = this.selected && this.selected.length ? this.selected[0] : null
            return fp === item.filepath
        },
        toggle(item, checked) {
            if (checked) {
                this.selected = [item.filepath]
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager',
                    action: 'select_shared_context',
                    filepath: item.filepath,
                }));
            } else {
                this.selected = null
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager',
                    action: 'clear_shared_context',
                }));
            }
        },
        create() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'create_shared_context',
                filename: this.newName || null,
            }));
            this.createDialog = false
        },
        cancelCreate() {
            this.createDialog = false
            this.newName = ''
        },
        remove(item) {
            const fp = item?.filepath
            if(!fp) return
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_shared_context',
                filepath: fp,
            }));
        },
        confirmCreateNewScene() {
            this.creatingNewScene = true;

            // Prepare scene_initialization data from current scene and shared context
            const currentScene = this.scene.data;
            const selectedSharedContext = this.selectedItem?.filename || null;
            const scene_initialization = {
                content_classification: currentScene.context || null,
                agent_persona_templates: currentScene.agent_persona_templates || null,
                writing_style_template: currentScene.writing_style_template || null,
                shared_context: selectedSharedContext,
                project_name: currentScene.project_name,
                active_characters: this.selectedSharedCharacters || [],
                intro_instructions: (this.newScenePremise || '').trim() || null,
                assets: currentScene.assets || null,
                intent_state: currentScene.story_intent ? { intent: currentScene.story_intent } : null,
            };

            // Create new scene with scene_initialization parameters
            this.getWebsocket().send(JSON.stringify({
                type: 'load_scene',
                file_path: '$NEW_SCENE$',
                scene_initialization: scene_initialization,
                reset: true
            }));

            //this.newSceneDialog = false;
            //this.creatingNewScene = false;
        },
        handleMessage(message) {

            if (message.type === 'system' && message.id === 'scene.loaded') {
                this.newSceneDialog = false;
                this.creatingNewScene = false;
            }

            // Handle world state manager messages
            if (message.type === 'world_state_manager') {
                if (message.action === 'shared_context_list') {
                    this.items = message.data.items || []
                    this.sharedCounts = message.data.shared_counts || { characters: 0, world_entries: 0 }
                    // Sync selection with current in-use item if present
                    const current = this.items.find(i => i.selected)
                    this.selected = current ? [current.filepath] : null
                } else if (message.action === 'character_list') {
                    // collect names where shared=true across active/inactive
                    const chars = message.data?.characters || {}
                    this.availableSharedCharacters = Object.values(chars)
                        .filter(c => c.shared)
                        .map(c => c.name)
                        .sort((a,b) => a.localeCompare(b))
                } else if (message.action === 'shared_context_selected' || message.action === 'shared_context_created' || message.action === 'shared_context_deleted' || message.action === 'shared_context_cleared') {
                    this.refresh()
                }
                return;
            }
        }
    },
    computed: {
        sharedCharactersCount() {
            return (this.sharedCounts && this.sharedCounts.characters) || 0
        },
        sharedWorldEntriesCount() {
            return (this.sharedCounts && this.sharedCounts.world_entries) || 0
        },
        selectedItem() {
            const fp = this.selected && this.selected.length ? this.selected[0] : null
            return fp ? this.items.find(i => i.filepath === fp) : null
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage)
        this.refresh()
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage)
    }
}
</script>


