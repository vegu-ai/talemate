<template>
    <div>
        <v-alert density="compact" variant="outlined" color="grey-darken-2" class="mb-4">
            <div class="text-muted">
                Episodes are alternative introductions that can be used to create new scenes. They are shared across all scenes in the <span class="font-weight-bold text-primary">{{ scene?.data?.project_name || 'project' }}</span> project.
            </div>
        </v-alert>

        <v-row class="episodes-layout">
            <!-- Left sidebar: List of episodes -->
            <v-col cols="12" md="4" class="episodes-list-sidebar">
                <div class="d-flex align-center pa-2 border-b">
                    <v-btn
                        color="primary"
                        variant="text"
                        size="small"
                        prepend-icon="mdi-plus"
                        @click="openAddDialog"
                        density="compact"
                    >
                        Add New
                    </v-btn>
                </div>
                <v-list 
                    density="compact" 
                    color="primary"
                    selectable
                    v-model:selected="selected"
                >
                    <v-list-item
                        v-for="(episode, index) in episodes"
                        :key="index"
                        :value="index"
                    >
                        <v-list-item-title class="text-wrap text-caption">
                            {{ episode.title || getPreviewText(episode.intro) }}
                        </v-list-item-title>
                        <v-list-item-subtitle v-if="episode.title" class="text-wrap text-caption">
                            {{ getPreviewText(episode.intro, 40) }}
                        </v-list-item-subtitle>
                    </v-list-item>
                    <v-list-item v-if="episodes.length === 0">
                        <v-list-item-title class="text-wrap text-caption text-muted">
                            No episodes available. Create one to get started.
                        </v-list-item-title>
                    </v-list-item>
                </v-list>
            </v-col>
            
            <!-- Right side: Preview -->
            <v-col cols="12" md="8" class="episode-preview">
                <v-card v-if="selectedIndex === null">
                    <v-card-text>
                        <v-alert color="muted" variant="text" density="compact" icon="mdi-arrow-left">
                            Select an episode from the list to preview
                        </v-alert>
                    </v-card-text>
                </v-card>
                <v-card v-else class="ma-4" elevation="7" color="muted" variant="tonal">
                    <v-card-text>
                        <div v-if="selectedEpisode?.title" class="text-h6 mb-2">{{ selectedEpisode.title }}</div>
                        <div v-if="selectedEpisode?.description" class="text-body-2 text-muted mb-2">{{ selectedEpisode.description }}</div>
                        <div class="intro-preview-text" v-html="renderedIntro"></div>
                    </v-card-text>
                </v-card>
            </v-col>
        </v-row>
        
        <v-card-actions>
            <v-btn variant="text" @click="refresh" prepend-icon="mdi-refresh" color="primary">
                Refresh
            </v-btn>
            <v-spacer></v-spacer>
            <v-btn 
                color="primary" 
                variant="text" 
                @click="openEditDialog(selectedIndex)"
                :disabled="selectedIndex === null"
                prepend-icon="mdi-pencil-outline"
            >
                Edit Episode
            </v-btn>
            <v-btn 
                color="delete" 
                variant="text" 
                @click="requestRemove(selectedIndex)"
                :disabled="selectedIndex === null"
                prepend-icon="mdi-close-circle-outline"
            >
                Delete Episode
            </v-btn>
        </v-card-actions>
    </div>
    
    <!-- Add/Edit episode dialog -->
    <v-dialog v-model="episodeDialog" max-width="900" :persistent="false">
        <v-card>
            <v-card-title>
                <v-icon size="small" class="mr-2" color="primary">{{ editingIndex !== null ? 'mdi-pencil' : 'mdi-plus-circle-outline' }}</v-icon>
                {{ editingIndex !== null ? 'Edit Episode' : 'Add New Episode' }}
            </v-card-title>
            <v-card-text>
                <v-form ref="episodeForm" v-model="episodeFormValid">
                    <v-row>
                        <v-col cols="12">
                            <v-text-field
                                v-model="episodeForm.title"
                                label="Title (optional)"
                                hint="A short title for this episode"
                                :rules="[]"
                            ></v-text-field>
                        </v-col>
                    </v-row>
                    <v-row>
                        <v-col cols="12">
                            <v-textarea
                                v-model="episodeForm.description"
                                label="Description (optional)"
                                hint="A brief description of this episode"
                                rows="2"
                                auto-grow
                                max-rows="4"
                                :rules="[]"
                            ></v-textarea>
                        </v-col>
                    </v-row>
                    <v-row>
                        <v-col cols="12">
                            <div class="d-flex align-center mb-2 intro-controls">
                                <v-spacer></v-spacer>
                                <ContextualGenerate 
                                    ref="contextualGenerate"
                                    uid="wsm.episode_intro"
                                    context="scene intro:scene intro" 
                                    :original="episodeForm.intro"
                                    :templates="templates"
                                    :generation-options="generationOptions"
                                    :history-aware="false"
                                    :specify-length="true"
                                    :requires-instructions="true"
                                    @generate="content => setIntroAndSave(content)"
                                />
                            </div>
                            <v-textarea
                                v-model="episodeForm.intro"
                                label="Introduction text"
                                hint="The introduction text for this episode. This will be displayed when creating a new scene from this episode."
                                rows="10"
                                auto-grow
                                max-rows="32"
                                :rules="[rules.required]"
                                required
                            ></v-textarea>
                        </v-col>
                    </v-row>
                </v-form>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="muted" variant="text" @click="closeEpisodeDialog">
                    Cancel
                </v-btn>
                <v-btn 
                    color="primary" 
                    variant="text" 
                    @click="saveEpisode"
                    :disabled="!episodeFormValid"
                    prepend-icon="mdi-check-circle-outline"
                >
                    {{ editingIndex !== null ? 'Update' : 'Create' }}
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
    
    <!-- Remove confirmation dialog -->
    <ConfirmActionPrompt
        ref="removeConfirm"
        action-label="Remove Episode"
        description="Are you sure you want to remove this episode?"
        icon="mdi-delete-outline"
        color="delete"
        @confirm="handleRemoveConfirmed"
    />
</template>

<script>
import { SceneTextParser } from '@/utils/sceneMessageRenderer';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import ContextualGenerate from './ContextualGenerate.vue';

export default {
    name: "WorldStateManagerSceneEpisodes",
    components: {
        ConfirmActionPrompt,
        ContextualGenerate,
    },
    props: {
        appConfig: Object,
        scene: Object,
        templates: Object,
        generationOptions: Object,
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    emits: ['create-scene', 'episode-selected'],
    data() {
        return {
            episodes: [],
            selected: [],
            parser: null,
            pendingRemoveIndex: null,
            episodeDialog: false,
            editingIndex: null,
            episodeForm: {
                title: '',
                description: '',
                intro: '',
            },
            episodeFormValid: false,
            rules: {
                required: value => !!value || 'Introduction text is required.',
            },
        }
    },
    computed: {
        selectedIndex() {
            return this.selected.length > 0 ? this.selected[0] : null;
        },
        selectedEpisode() {
            if (this.selectedIndex === null || !this.episodes[this.selectedIndex]) {
                return null;
            }
            return this.episodes[this.selectedIndex];
        },
        renderedIntro() {
            if (this.selectedIndex === null || !this.episodes[this.selectedIndex]) {
                return '';
            }
            
            const episode = this.episodes[this.selectedIndex];
            if (!this.parser) {
                this.initParser();
            }
            
            try {
                return this.parser.parse(episode.intro);
            } catch (e) {
                console.error('Error rendering episode intro:', e);
                return episode.intro;
            }
        },
    },
    watch: {
        selectedIndex() {
            this.$emit('episode-selected', this.selectedEpisode);
        }
    },
    methods: {
        initParser() {
            const sceneConfig = this.appConfig?.appearance?.scene || {};
            const actorStyles = sceneConfig.actor_messages || sceneConfig.character_messages || {};
            const narratorStyles = sceneConfig.narrator_messages || {};
            
            this.parser = new SceneTextParser({
                quotes: sceneConfig.quotes,
                emphasis: sceneConfig.emphasis || narratorStyles,
                parentheses: sceneConfig.parentheses || narratorStyles,
                brackets: sceneConfig.brackets || narratorStyles,
            });
        },
        getPreviewText(text, maxLength = 60) {
            if (!text) return '';
            const cleaned = text.replace(/\n/g, ' ').trim();
            if (cleaned.length <= maxLength) {
                return cleaned;
            }
            return cleaned.substring(0, maxLength) + '...';
        },
        refresh() {
            this.loadEpisodes();
        },
        loadEpisodes() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_episodes',
            }));
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action === 'episodes') {
                const oldSelectedIndex = this.selectedIndex;
                this.episodes = message.data.episodes || [];
                // Clear selection if the removed item was selected or if selection is out of bounds
                if (oldSelectedIndex !== null && oldSelectedIndex >= this.episodes.length) {
                    this.selected = [];
                }
                this.$emit('episode-selected', this.selectedEpisode);
            }
        },
        openAddDialog() {
            this.editingIndex = null;
            this.episodeForm = {
                title: '',
                description: '',
                intro: '',
            };
            this.episodeDialog = true;
        },
        openEditDialog(index) {
            if (index === null || !this.episodes[index]) {
                return;
            }
            const episode = this.episodes[index];
            this.editingIndex = index;
            this.episodeForm = {
                title: episode.title || '',
                description: episode.description || '',
                intro: episode.intro || '',
            };
            this.episodeDialog = true;
        },
        closeEpisodeDialog() {
            this.episodeDialog = false;
            this.editingIndex = null;
            this.episodeForm = {
                title: '',
                description: '',
                intro: '',
            };
        },
        setIntroAndSave(content) {
            this.episodeForm.intro = content;
        },
        saveEpisode() {
            if (!this.$refs.episodeForm) {
                return;
            }
            
            this.$refs.episodeForm.validate();
            if (!this.episodeFormValid) {
                return;
            }
            
            if (!this.episodeForm.intro || !this.episodeForm.intro.trim()) {
                return;
            }
            
            const payload = {
                intro: this.episodeForm.intro.trim(),
            };
            
            if (this.episodeForm.title && this.episodeForm.title.trim()) {
                payload.title = this.episodeForm.title.trim();
            }
            
            if (this.episodeForm.description && this.episodeForm.description.trim()) {
                payload.description = this.episodeForm.description.trim();
            }
            
            if (this.editingIndex !== null) {
                // Update existing episode
                payload.index = this.editingIndex;
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager',
                    action: 'update_episode',
                    ...payload,
                }));
            } else {
                // Add new episode
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager',
                    action: 'add_episode',
                    ...payload,
                }));
            }
            
            this.closeEpisodeDialog();
        },
        requestRemove(index) {
            this.pendingRemoveIndex = index;
            if (this.$refs.removeConfirm) {
                this.$refs.removeConfirm.initiateAction({ index });
            }
        },
        handleRemoveConfirmed(params) {
            if (this.pendingRemoveIndex !== null) {
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager',
                    action: 'remove_episode',
                    index: this.pendingRemoveIndex,
                }));
                this.pendingRemoveIndex = null;
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.initParser();
        this.refresh();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>

<style scoped>
.episodes-layout {
    min-height: 500px;
    max-height: 900px;
}

.episodes-list-sidebar {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    max-height: 900px;
}

.episodes-list-sidebar .v-list {
    overflow-y: auto;
    flex: 1;
    min-height: 0;
}

.border-b {
    border-bottom: 1px solid rgba(var(--v-border-opacity), var(--v-border-opacity));
    flex-shrink: 0;
}

.episode-preview {
    overflow-y: auto;
    max-height: 900px;
}

.intro-preview-text {
    white-space: pre-wrap;
    word-wrap: break-word;
    overflow-wrap: break-word;
    line-height: 1.5;
}

.intro-controls {
    gap: 8px;
}

</style>
