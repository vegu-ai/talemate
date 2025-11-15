<template>
    <v-dialog v-model="dialog" max-width="1200px" scrollable>
        <v-card>
            <v-card-title>
                <v-icon class="mr-2">mdi-format-list-bulleted</v-icon>
                Browse Intro Alternatives
            </v-card-title>
            <v-card-text>
                <v-row class="intro-browser-layout">
                    <!-- Left sidebar: List of alternatives -->
                    <v-col cols="12" md="4" class="intro-list-sidebar">
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
                            <v-spacer></v-spacer>
                            <v-btn
                                color="primary"
                                variant="text"
                                size="small"
                                prepend-icon="mdi-content-copy"
                                @click="addFromCurrent"
                                density="compact"
                                :disabled="!currentIntro || !currentIntro.trim()"
                            >
                                Add Current
                            </v-btn>
                        </div>
                        <v-list 
                            density="compact" 
                            color="primary"
                            selectable
                            v-model:selected="selected"
                        >
                            <v-list-item
                                v-for="(version, index) in introVersions"
                                :key="index"
                                :value="index"
                            >
                                <v-list-item-title class="text-wrap text-caption">
                                    {{ getPreviewText(version) }}
                                </v-list-item-title>
                            </v-list-item>
                            <v-list-item v-if="introVersions.length === 0">
                                <v-list-item-title class="text-wrap text-caption text-muted">
                                    No alternative introductions available.
                                </v-list-item-title>
                            </v-list-item>
                        </v-list>
                    </v-col>
                    
                    <!-- Right side: Preview -->
                    <v-col cols="12" md="8" class="intro-preview">
                        <v-card v-if="selectedIndex === null">
                            <v-card-text>
                                <v-alert color="muted" variant="text" density="compact" icon="mdi-arrow-left">
                                    Select an intro from the list to preview
                                </v-alert>
                            </v-card-text>
                        </v-card>
                        <v-card v-else class="ma-4" elevation="7" color="muted" variant="tonal">
                            <v-card-text class="intro-preview-text" v-html="renderedIntro"></v-card-text>
                        </v-card>
                    </v-col>
                </v-row>
            </v-card-text>
            <v-card-actions>
                <v-btn color="muted" variant="text" @click="close">
                    Close
                </v-btn>
                <v-spacer></v-spacer>
                <v-btn 
                    color="delete" 
                    variant="text" 
                    @click="requestRemove(selectedIndex)"
                    :disabled="selectedIndex === null"
                    prepend-icon="mdi-delete-outline"
                >
                    Delete Selected
                </v-btn>
                <v-btn 
                    color="primary" 
                    variant="text" 
                    @click="applySelected"
                    :disabled="selectedIndex === null"
                >
                    Use Selected
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
    
    <!-- Add new intro version dialog -->
    <RequestInput
        ref="addIntroInput"
        title="Add New Intro Alternative"
        icon="mdi-plus-circle-outline"
        input-type="multiline"
        placeholder="Enter the intro text..."
        instructions="Enter a new alternative introduction for this scene."
        :size="800"
        @continue="handleAddNewIntro"
    />
    
    <!-- Remove confirmation dialog -->
    <ConfirmActionPrompt
        ref="removeConfirm"
        action-label="Remove Intro Alternative"
        description="Are you sure you want to remove this intro alternative?"
        icon="mdi-delete-outline"
        color="delete"
        @confirm="handleRemoveConfirmed"
    />
</template>

<script>
import { SceneTextParser } from '@/utils/sceneMessageRenderer';
import RequestInput from './RequestInput.vue';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';

export default {
    name: "WorldStateManagerSceneIntroAlternatives",
    components: {
        RequestInput,
        ConfirmActionPrompt,
    },
    props: {
        appConfig: Object,
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    emits: ['selected'],
    data() {
        return {
            dialog: false,
            introVersions: [],
            selected: [],
            currentIntro: '',
            parser: null,
            pendingRemoveIndex: null,
        }
    },
    computed: {
        selectedIndex() {
            return this.selected.length > 0 ? this.selected[0] : null;
        },
        renderedIntro() {
            if (this.selectedIndex === null || !this.introVersions[this.selectedIndex]) {
                return '';
            }
            
            const intro = this.introVersions[this.selectedIndex];
            if (!this.parser) {
                this.initParser();
            }
            
            try {
                return this.parser.parse(intro);
            } catch (e) {
                console.error('Error rendering intro:', e);
                return intro;
            }
        }
    },
    methods: {
        initParser() {
            const characterStyles = this.appConfig?.appearance?.scene?.character_messages || {};
            const narratorStyles = this.appConfig?.appearance?.scene?.narrator_messages || {};
            
            this.parser = new SceneTextParser({
                quotes: characterStyles,
                emphasis: narratorStyles,
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
        open(currentIntro) {
            this.dialog = true;
            this.currentIntro = currentIntro;
            this.selected = [];
            this.initParser();
            this.loadIntroVersions();
        },
        close() {
            this.dialog = false;
            this.selected = [];
        },
        loadIntroVersions() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_intro_versions',
            }));
        },
        applySelected() {
            if (this.selectedIndex === null) {
                return;
            }
            
            const selectedIntro = this.introVersions[this.selectedIndex];
            
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_intro',
                intro: selectedIntro,
            }));
            
            this.$emit('selected', selectedIntro);
            this.close();
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action === 'intro_versions') {
                const oldSelectedIndex = this.selectedIndex;
                this.introVersions = message.data.intro_versions || [];
                // Clear selection if the removed item was selected or if selection is out of bounds
                if (oldSelectedIndex !== null && oldSelectedIndex >= this.introVersions.length) {
                    this.selected = [];
                }
            }
        },
        openAddDialog() {
            if (this.$refs.addIntroInput) {
                this.$refs.addIntroInput.openDialog({ input: '' });
            }
        },
        handleAddNewIntro(intro) {
            if (!intro || !intro.trim()) {
                return;
            }
            
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'add_intro_version',
                intro: intro.trim(),
            }));
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
                    action: 'remove_intro_version',
                    index: this.pendingRemoveIndex,
                }));
                this.pendingRemoveIndex = null;
            }
        },
        addFromCurrent() {
            if (!this.currentIntro) {
                return;
            }
            
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'add_intro_version_from_current',
            }));
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.initParser();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>

<style scoped>
.intro-browser-layout {
    min-height: 500px;
    max-height: 900px;
}

.border-b {
    border-bottom: 1px solid rgba(var(--v-border-opacity), var(--v-border-opacity));
}

.intro-preview {
    overflow-y: auto;
}

.intro-preview-text {
    white-space: pre-wrap;
    word-wrap: break-word;
    overflow-wrap: break-word;
    line-height: 1.5;
}

</style>
