<template>
    <v-toolbar density="compact" flat color="mutedbg">
        <v-toolbar-title class="text-subtitle-2 text-muted">
            <v-icon class="mr-1">mdi-bullhorn</v-icon> Scene Direction
        </v-toolbar-title>
        
        <DirectorActionsMenu 
            mode="scene_direction"
            :app-busy="appBusy"
            :app-ready="appReady"
        />
        
        <v-spacer></v-spacer>
        <v-btn @click="openWorldStateManager('scene','director')" color="primary" size="small">Manage</v-btn>
    </v-toolbar>
    <v-divider class="mb-2"></v-divider>
    <v-card>
        <v-card-text>
            <v-select 
                :items="sceneTypes" 
                v-model="intent.phase.scene_type" 
                label="Scene Type" 
                class="text-caption" 
                density="compact" 
                @update:model-value="updateSceneIntent()"
            ></v-select>
            
            <ContextualGenerate 
                ref="phaseIntentGenerate"
                uid="wsm.scene_phase_intent"
                :context="'scene phase intent:' + intent.phase.scene_type" 
                :original="intent.phase.intent"
                :length="256"
                :specify-length="true"
                @generate="content => setAndUpdatePhaseIntent(content)"
            />
            <v-textarea 
                density="compact" 
                v-model="intent.phase.intent" 
                class="text-caption" 
                hide-details 
                rows="4" 
                max-rows="15" 
                auto-grow
                :color="dirty['intent.phase.intent'] ? 'dirty' : ''"
                @update:model-value="dirty['intent.phase.intent'] = true"
                @blur="updateSceneIntent()"
            ></v-textarea>
        </v-card-text>
    </v-card>

    <v-divider class="my-2"></v-divider>

    <v-toolbar density="compact" flat color="mutedbg">
        <v-toolbar-title class="text-subtitle-2 text-muted">
            <v-icon class="mr-1">mdi-timeline-text</v-icon> Direction Timeline
        </v-toolbar-title>
        <v-spacer></v-spacer>
        <v-chip v-if="directionTokenTotal !== null" size="x-small" color="primary" label class="ml-2 mr-4">Tokens {{ directionTokenTotal }}</v-chip>
        <confirm-action-inline
            v-if="directionMessages.length > 0"
            action-label="Clear"
            confirm-label="Confirm Clear (Forgets Actions)"
            icon="mdi-delete-sweep"
            color="error"
            size="small"
            @confirm="clearDirectionHistory"
        />
    </v-toolbar>
    <v-divider class="mb-2"></v-divider>

    <v-card>
        <v-card-text>
            <DirectorConsoleChatMessages
                :messages="directionMessages"
                :readonly="true"
                :app-busy="appBusy"
                :app-ready="appReady"
            >
                <template #empty>
                    No scene direction messages yet
                </template>
            </DirectorConsoleChatMessages>
        </v-card-text>
    </v-card>
</template>

<script>
import ContextualGenerate from './ContextualGenerate.vue';
import DirectorActionsMenu from './DirectorActionsMenu.vue';
import DirectorConsoleChatMessages from './DirectorConsoleChatMessages.vue';
import ConfirmActionInline from './ConfirmActionInline.vue';

export default {
    name: 'DirectorConsoleSceneDirection',
    components: {
        ContextualGenerate,
        DirectorActionsMenu,
        DirectorConsoleChatMessages,
        ConfirmActionInline,
    },
    props: {
        scene: Object,
        appBusy: {
            type: Boolean,
            default: false,
        },
        appReady: {
            type: Boolean,
            default: true,
        },
    },
    inject: [
        'openWorldStateManager',
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    data() {
        return {
            dirty: {},
            intent: {
                intent: null,
                phase: {
                    intent: null,
                    scene_type: null,
                },
                scene_types: {},
                start: 0,
            },
            directionId: null,
            directionMessages: [],
            directionTokenTotal: null,
        }
    },
    computed: {
        sceneTypes() {
            if(!this.intent || !this.intent.scene_types) {
                return [];
            }

            const types = [];
            for(const key in this.intent.scene_types) {
                types.push({
                    value: this.intent.scene_types[key].id,
                    title: this.intent.scene_types[key].name,
                });
            }

            return types;
        },
    },
    methods: {
        requestSceneDirectionHistory() {
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'scene_direction_history',
            }));
        },
        clearDirectionHistory() {
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'scene_direction_clear',
            }));
        },
        resetDirectionForNewScene() {
            this.directionId = null;
            this.directionMessages = [];
            this.directionTokenTotal = null;
            this.requestSceneDirectionHistory();
        },
        hasTrailingLoading() {
            if(!this.directionMessages || this.directionMessages.length === 0) return false;
            const last = this.directionMessages[this.directionMessages.length - 1];
            return !!(last && last.source === 'director' && last.loading);
        },
        removeTrailingPlaceholder() {
            if(this.hasTrailingLoading()) {
                this.directionMessages.pop();
            }
        },
        ensureTrailingPlaceholder(label) {
            if(this.hasTrailingLoading()) return;
            this.directionMessages.push({ source: 'director', message: '', loading: true, loading_label: label || null });
        },
        applyDirectionAppend(newMessages) {
            const msgs = newMessages || [];
            if(msgs.length === 0) return;
            this.removeTrailingPlaceholder();
            for(let i = 0; i < msgs.length; i++) {
                this.directionMessages.push(msgs[i]);
            }
        },
        setAndUpdatePhaseIntent(content) {
            this.intent.phase.intent = content;
            this.dirty['intent.phase.intent'] = true;
            this.updateSceneIntent();
        },
        updateSceneIntent() {
            if(!this.intent || !this.intent.intent) {
                return;
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_scene_intent',
                ...this.intent,
            }));
        },
        getSceneIntent() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_scene_intent',
            }));
        },
        handleMessage(message) {
            // Reset when a new scene loads
            if(message.type === 'system' && message.id === 'scene.loaded') {
                this.resetDirectionForNewScene();
                this.getSceneIntent();
                return;
            }

            // Dedicated scene intent push updates
            if (message.type === 'scene_intent' && message.action === 'updated') {
                const hasDirty = Object.values(this.dirty || {}).some(Boolean);
                if (!hasDirty) {
                    this.intent = message.data;
                }
                return;
            }

            if (message.type === 'world_state_manager' && message.action === 'get_scene_intent') {
                this.intent = message.data;
                return;
            }

            // Scene direction read-only feed
            if(message.type === 'director' && message.action === 'scene_direction_history') {
                this.directionId = message.direction_id || null;
                this.directionMessages = message.messages || [];
                this.directionTokenTotal = (typeof message.token_total === 'number') ? message.token_total : null;
                return;
            }
            if(message.type === 'director' && message.action === 'scene_direction_append') {
                // Ignore updates for a different direction instance if we already have one
                if(this.directionId && message.direction_id && message.direction_id !== this.directionId) return;
                if(!this.directionId && message.direction_id) this.directionId = message.direction_id;
                this.applyDirectionAppend(message.messages || []);
                if(typeof message.token_total === 'number') {
                    this.directionTokenTotal = message.token_total;
                }
                return;
            }
            if(message.type === 'director' && message.action === 'scene_direction_compacting') {
                // Show a temporary placeholder while compaction runs; history will refresh after
                if(this.directionId && message.direction_id && message.direction_id !== this.directionId) return;
                if(!this.directionId && message.direction_id) this.directionId = message.direction_id;
                this.ensureTrailingPlaceholder('Compacting direction history...');
                return;
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.getSceneIntent();
        this.requestSceneDirectionHistory();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>

<style scoped>
</style>

