<template>
    <div>
        <v-row>
            <v-col cols="12" xl="8" xxl="5">
                <v-card>
                    <v-alert density="compact" variant="outlined" color="muted" class="ma-4">
                        <template v-slot:prepend>
                            <v-icon color="primary">mdi-earth</v-icon>
                        </template>
                        Share specific character and world entries across individual <span class="font-weight-bold text-primary">{{ scene.data.project_name }}</span> scenes.
                    </v-alert>

                    <v-card class="ma-4" elevation="3" variant="tonal" color="grey-darken-3">
                        <v-card-text class="text-muted" >
                            <div v-if="selectedItem">
                                This scene is linked to the <span class="font-weight-bold text-primary">{{ selectedItem.filename }}</span> shared context.

                                <v-chip class="mr-2" label color="highlight6" prepend-icon="mdi-account">{{ sharedCharactersCount }} shared characters</v-chip>
                                <v-chip class="mr-2" label color="highlight6" prepend-icon="mdi-text-box-search">{{ sharedWorldEntriesCount }} shared world entries</v-chip>

                                <v-btn color="primary" variant="text" prepend-icon="mdi-script-text" @click="createNewScene" :disabled="!scene?.data?.saved">
                                    <v-tooltip activator="parent">{{ scene?.data?.saved ? 'Create a new scene with the same shared context.' : 'Save the scene first to create a new scene.' }}</v-tooltip>
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

        <v-dialog v-model="createDialog" width="480">
            <v-card>
                <v-card-title>
                    <v-icon size="small" class="mr-2">mdi-book-plus</v-icon>
                    Create Shared Context
                </v-card-title>
                <v-card-text>
                    <v-text-field v-model="newName" label="Filename" hint="Will be stored as .json inside the scene's shared-context folder" @keyup.enter="create" />
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn variant="tonal" @click="createDialog=false">Cancel</v-btn>
                    <v-btn color="primary" @click="create">Create</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </div>
</template>

<script>
import ConfirmActionInline from './ConfirmActionInline.vue';
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
            items: [],
            selected: null,
            createDialog: false,
            newName: '',
            sharedCounts: { characters: 0, world_entries: 0 },
        }
    },
    methods: {
        refresh() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'list_shared_contexts',
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
        remove(item) {
            const fp = item?.filepath
            if(!fp) return
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_shared_context',
                filepath: fp,
            }));
        },
        createNewScene() {
            if (!this.scene?.data?.saved) {
                return;
            }

            // Prepare inheritance data from current scene and shared context
            const currentScene = this.scene.data;
            const selectedSharedContext = this.selectedItem?.filename || null;
            const inheritance = {
                content_classification: currentScene.context || null,
                agent_persona_templates: currentScene.agent_persona_templates || null,
                writing_style_template: currentScene.writing_style_template || null,
                shared_context: selectedSharedContext,
                project_name: currentScene.project_name,
            }

            console.debug('inheritance', inheritance)

            // Create new scene with inheritance parameters
            this.getWebsocket().send(JSON.stringify({
                type: 'load_scene',
                file_path: '$NEW_SCENE$',
                inheritance: inheritance,
                reset: true
            }));
        },
        handleMessage(message) {
            if (message.type === 'world_state_manager') {
                if (message.action === 'shared_context_list') {
                    this.items = message.data.items || []
                    this.sharedCounts = message.data.shared_counts || { characters: 0, world_entries: 0 }
                    // Sync selection with current in-use item if present
                    const current = this.items.find(i => i.selected)
                    this.selected = current ? [current.filepath] : null
                } else if (message.action === 'shared_context_selected' || message.action === 'shared_context_created' || message.action === 'shared_context_deleted' || message.action === 'shared_context_cleared') {
                    this.refresh()
                }
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


