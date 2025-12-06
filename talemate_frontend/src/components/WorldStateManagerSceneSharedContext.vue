<template>
    <!-- Shared Context Section -->
    <v-card class="mt-4">
        <v-card-title class="d-flex align-center">
            <v-icon class="mr-2" color="highlight6">mdi-earth</v-icon>
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
                                    <v-menu>
                                        <template v-slot:activator="{ props }">
                                            <v-chip 
                                                v-bind="props"
                                                class="mr-2" 
                                                label 
                                                color="highlight6" 
                                                prepend-icon="mdi-account"
                                                style="cursor: pointer;"
                                            >
                                                {{ sharedCharactersCount }} shared characters
                                            </v-chip>
                                        </template>
                                        <v-list>
                                            <v-list-item @click="shareAllCharacters">
                                                <template v-slot:prepend>
                                                    <v-icon>mdi-earth</v-icon>
                                                </template>
                                                <v-list-item-title>Share all characters</v-list-item-title>
                                            </v-list-item>
                                            <v-list-item @click="unshareAllCharacters">
                                                <template v-slot:prepend>
                                                    <v-icon>mdi-earth-off</v-icon>
                                                </template>
                                                <v-list-item-title>Unshare all characters</v-list-item-title>
                                            </v-list-item>
                                        </v-list>
                                    </v-menu>
                                    <v-menu>
                                        <template v-slot:activator="{ props }">
                                            <v-chip 
                                                v-bind="props"
                                                class="mr-2" 
                                                label 
                                                color="highlight6" 
                                                prepend-icon="mdi-text-box-search"
                                                style="cursor: pointer;"
                                            >
                                                {{ sharedWorldEntriesCount }} shared world entries
                                            </v-chip>
                                        </template>
                                        <v-list>
                                            <v-list-item @click="shareAllWorldEntries">
                                                <template v-slot:prepend>
                                                    <v-icon>mdi-earth</v-icon>
                                                </template>
                                                <v-list-item-title>Share all world entries</v-list-item-title>
                                            </v-list-item>
                                            <v-list-item @click="unshareAllWorldEntries">
                                                <template v-slot:prepend>
                                                    <v-icon>mdi-earth-off</v-icon>
                                                </template>
                                                <v-list-item-title>Unshare all world entries</v-list-item-title>
                                            </v-list-item>
                                        </v-list>
                                    </v-menu>
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
    emits: ['selected-changed'],
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
                this.$emit('selected-changed', this.selectedItem)
            } else {
                this.selected = null
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager',
                    action: 'clear_shared_context',
                }));
                this.$emit('selected-changed', null)
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
        shareAllCharacters() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'share_all_characters',
            }));
        },
        unshareAllCharacters() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'unshare_all_characters',
            }));
        },
        shareAllWorldEntries() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'share_all_world_entries',
            }));
        },
        unshareAllWorldEntries() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'unshare_all_world_entries',
            }));
        },
        handleMessage(message) {
            // Handle world state manager messages
            if (message.type === 'world_state_manager') {
                if (message.action === 'shared_context_list') {
                    this.items = message.data.items || []
                    this.sharedCounts = message.data.shared_counts || { characters: 0, world_entries: 0 }
                    // Sync selection with current in-use item if present
                    const current = this.items.find(i => i.selected)
                    this.selected = current ? [current.filepath] : null
                    this.$emit('selected-changed', this.selectedItem)
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
