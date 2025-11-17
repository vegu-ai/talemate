<template>
    <div :style="{ maxWidth: MAX_CONTENT_WIDTH }">
        <!-- New Scene Section -->
        <v-row>
            <v-col cols="12">
                <v-card elevation="2" class="mt-4" color="grey-darken-2" variant="tonal">
                    <v-card-text class="d-flex justify-end align-center flex-wrap">
                        <v-chip 
                            v-if="selectedItem" 
                            color="highlight6" 
                            label
                            variant="tonal" 
                            prepend-icon="mdi-earth"
                            class="mr-2"
                        >
                            {{ selectedItem.filename }}
                        </v-chip>
                        <v-chip 
                            v-if="selectedEpisode" 
                            color="highlight2" 
                            label
                            variant="tonal" 
                            prepend-icon="mdi-book-open-variant"
                            class="mr-2"
                        >
                            {{ selectedEpisode.title || getEpisodePreview(selectedEpisode.intro) }}
                        </v-chip>
                        <v-btn 
                            color="primary" 
                            variant="text" 
                            prepend-icon="mdi-script-text" 
                            @click="openNewSceneDialog"
                        >
                            <v-tooltip activator="parent">
                                <span v-if="selectedItem && selectedEpisode">Create a new scene with shared context and selected episode</span>
                                <span v-else-if="selectedItem">Create a new scene with shared context</span>
                                <span v-else-if="selectedEpisode">Create a new scene from selected episode</span>
                                <span v-else>Create a new scene (intro will be generated from premise instructions)</span>
                            </v-tooltip>
                            New Scene
                        </v-btn>
                    </v-card-text>
                </v-card>
            </v-col>
        </v-row>

        <!-- Shared Context Section -->
        <v-row>
            <v-col cols="12">
                <v-card class="mt-4">
                    <v-card-title class="d-flex align-center">
                        <v-icon class="mr-2">mdi-earth</v-icon>
                        Shared Context
                    </v-card-title>

                    <v-row class="ma-0">
                        <!-- Left Column: Shared Context List -->
                        <v-col cols="12" md="4">
                            <v-card-text class="pa-4">
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
                                <v-card-actions class="pa-0 mt-2">
                                    <v-btn color="primary" prepend-icon="mdi-refresh" size="small" @click="refresh">Refresh</v-btn>
                                    <v-spacer></v-spacer>
                                    <v-btn color="primary" prepend-icon="mdi-plus" size="small" @click="openCreateDialog">New</v-btn>
                                </v-card-actions>
                            </v-card-text>
                        </v-col>

                        <!-- Right Column: Shared Context Details -->
                        <v-col cols="12" md="8">
                            <v-card-text class="pa-4">
                                <v-alert density="compact" variant="outlined" color="grey-darken-2" class="mb-4">
                                    <template v-slot:prepend>
                                        <v-icon color="primary">mdi-earth</v-icon>
                                    </template>
                                    <div class="text-muted">
                                        Share specific characters, world entries and history across connected <span class="font-weight-bold text-primary">{{ scene.data.project_name }}</span> scenes.
                                    </div>
                                </v-alert>

                                <v-card elevation="3" variant="tonal" color="grey-darken-3">
                                    <v-card-text class="text-muted" >
                                        <div v-if="selectedItem">
                                            <div class="mb-2">
                                                This scene is linked to the <span class="font-weight-bold text-primary">{{ selectedItem.filename }}</span> shared context.
                                            </div>
                                            <div class="d-flex align-center flex-wrap">
                                                <v-chip class="mr-2" label color="highlight6" prepend-icon="mdi-account">{{ sharedCharactersCount }} shared characters</v-chip>
                                                <v-chip class="mr-2" label color="highlight6" prepend-icon="mdi-text-box-search">{{ sharedWorldEntriesCount }} shared world entries</v-chip>
                                            </div>
                                        </div>
                                        <div v-else>
                                            No shared context linked. <span v-if="items.length">You can link one by selecting a shared context file from the list.</span><span v-else><v-btn color="primary" variant="text" prepend-icon="mdi-plus" @click="openCreateDialog">Create shared context</v-btn></span>
                                        </div>
                                    </v-card-text>
                                </v-card>
                            </v-card-text>
                        </v-col>
                    </v-row>
                </v-card>
            </v-col>
        </v-row>
        
        <!-- Episodes Section -->
        <v-row class="mt-4">
            <v-col cols="12">
                <v-card class="mb-4">
                    <v-card-title class="d-flex align-center">
                        <v-icon class="mr-2">mdi-book-open-variant</v-icon>
                        Episodes
                    </v-card-title>
                    <v-card-text class="mt-4">
                        <WorldStateManagerSceneEpisodes
                            ref="episodes"
                            :app-config="appConfig"
                            :scene="scene"
                            :templates="templates"
                            :generation-options="generationOptions"
                            @episode-selected="handleEpisodeSelected"
                        />
                    </v-card-text>
                </v-card>
            </v-col>
        </v-row>
    </div>

    <!-- Create Shared Context Dialog -->
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
                    Create New Scene
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
                    <v-alert v-if="selectedItem" density="compact" variant="outlined" color="highlight6" class="mb-4">
                        <template v-slot:prepend>
                            <v-icon color="highlight6">mdi-earth</v-icon>
                        </template>
                        <div class="text-muted">
                            The new scene will be linked to the <span class="font-weight-bold text-highlight6">{{ selectedItem.filename }}</span> shared context.
                        </div>
                    </v-alert>
                    <v-alert v-if="!selectedItem" density="compact" variant="outlined" color="warning" class="mb-4">
                        <template v-slot:prepend>
                            <v-icon color="warning">mdi-information</v-icon>
                        </template>
                        <div class="text-muted">
                            <strong>World sharing is off.</strong> All characters from the current scene will be copied to the new scene. You can select which characters to activate below.
                        </div>
                    </v-alert>
                    <v-alert v-if="!selectedItem" density="compact" variant="tonal" color="info" class="mb-4">
                        <template v-slot:prepend>
                            <v-icon color="info">mdi-information-outline</v-icon>
                        </template>
                        <div class="text-muted">
                            <strong>Recommendation:</strong> Switch shared world on for easier management of characters across scenes in the same world.
                        </div>
                    </v-alert>
                    <v-alert v-if="selectedEpisode" density="compact" variant="outlined" color="primary" class="mb-4">
                        <template v-slot:prepend>
                            <v-icon color="primary">mdi-book-open-variant</v-icon>
                        </template>
                        <div class="text-muted">
                            <strong>Selected Episode:</strong> {{ selectedEpisode.title || 'Untitled Episode' }}
                            <div v-if="selectedEpisode.description" class="mt-1 text-caption">{{ selectedEpisode.description }}</div>
                        </div>
                    </v-alert>

                    <v-textarea
                        v-if="!selectedEpisode"
                        v-model="newScenePremise"
                        rows="4"
                        auto-grow
                        max-rows="12"
                        label="Instructions for new premise. (optional)"
                        hint="Short instructions for what kind of introduction to generate for the new scene."
                    />
                    <v-alert v-else density="compact" variant="text" color="muted" class="mb-4">
                        <div class="text-muted">
                            The episode's introduction will be used as the scene intro. Premise instructions are not needed.
                        </div>
                    </v-alert>

                    <div class="mt-4">
                        <div v-if="availableCharacters.length">
                            <v-combobox
                                v-model="selectedSharedCharacters"
                                :items="availableCharacters"
                                :label="selectedItem ? 'Select characters to activate' : 'Select characters to activate (all characters will be copied)'"
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
                            <v-card-text class="text-grey">
                                <span v-if="selectedItem">There are no shared characters in the shared context.</span>
                                <span v-else>There are no characters in the current scene.</span>
                            </v-card-text>
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
import WorldStateManagerSceneEpisodes from './WorldStateManagerSceneEpisodes.vue';
import { MAX_CONTENT_WIDTH } from '@/constants';
export default {
    name: 'WorldStateManagerSceneSharedContext',
    props: {
        scene: Object,
        appConfig: Object,
        templates: Object,
        generationOptions: Object,
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    components: {
        ConfirmActionInline,
        WorldStateManagerSceneEpisodes,
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
            availableAllCharacters: [],
            selectedSharedCharacters: [],
            creatingNewScene: false,
            selectedEpisode: null,
            characterData: null,
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
            this.availableAllCharacters = []
            this.characterData = null
            this.creatingNewScene = false
            this.newSceneDialog = true

            // Request character list (for both shared context and all characters)
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_list',
            }));
            
            // Request character data (for copying when world sharing is off)
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_data',
            }));
        },
        handleEpisodeSelected(episode) {
            this.selectedEpisode = episode;
        },
        getEpisodePreview(intro, maxLength = 40) {
            if (!intro) return '';
            const cleaned = intro.replace(/\n/g, ' ').trim();
            if (cleaned.length <= maxLength) {
                return cleaned;
            }
            return cleaned.substring(0, maxLength) + '...';
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
            
            // If world sharing is off, copy ALL character_data (not just selected ones)
            // We always copy all characters when world sharing is off, regardless of which are selected for activation
            const character_data = !selectedSharedContext && this.characterData 
                ? { ...this.characterData }
                : null;
            
            // Filter active_characters to only include characters that will exist in the new scene
            // When world sharing is ON: only include shared characters
            // When world sharing is OFF: only include characters that exist in character_data
            let active_characters = this.selectedSharedCharacters || [];
            if (selectedSharedContext) {
                // World sharing ON: only include shared characters
                active_characters = active_characters.filter(name => 
                    this.availableSharedCharacters.includes(name)
                );
            } else if (character_data) {
                // World sharing OFF: only include characters that exist in character_data
                active_characters = active_characters.filter(name => 
                    name in character_data
                );
            }
            
            const scene_initialization = {
                content_classification: currentScene.context || null,
                agent_persona_templates: currentScene.agent_persona_templates || null,
                writing_style_template: currentScene.writing_style_template || null,
                shared_context: selectedSharedContext,
                project_name: currentScene.project_name,
                active_characters: active_characters,
                character_data: character_data,
                intro: this.selectedEpisode?.intro || null,
                intro_instructions: (!this.selectedEpisode && this.newScenePremise) ? this.newScenePremise.trim() : null,
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
                    // collect all character names (for when world sharing is off)
                    this.availableAllCharacters = Object.values(chars)
                        .map(c => c.name)
                        .sort((a,b) => a.localeCompare(b))
                    
                    // Auto-select player character if dialog is open
                    if (this.newSceneDialog) {
                        const playerCharacter = Object.values(chars).find(c => c.is_player)
                        if (playerCharacter && !this.selectedSharedCharacters.includes(playerCharacter.name)) {
                            this.selectedSharedCharacters.push(playerCharacter.name)
                        }
                    }
                } else if (message.action === 'character_data') {
                    // Store character data for copying when world sharing is off
                    this.characterData = message.data?.character_data || null
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
        },
        availableCharacters() {
            // If world sharing is on, show only shared characters
            // If world sharing is off, show all characters
            return this.selectedItem ? this.availableSharedCharacters : this.availableAllCharacters
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


