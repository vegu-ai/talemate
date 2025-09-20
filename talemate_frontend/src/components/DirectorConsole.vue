<template>

    <v-tabs v-model="activeTab" density="compact" align-tabs="center">
        <v-tooltip text="Scene Direction" location="top">
            <template #activator="{ props }">
                <v-tab v-bind="props" value="phase" :ripple="false" color="primary">
                    <v-icon>mdi-bullhorn</v-icon>
                </v-tab>
            </template>
        </v-tooltip>

        <v-tooltip text="Actions taken by the director" location="top">
            <template #activator="{ props }">
                <v-tab v-bind="props" value="actions" :ripple="false" color="primary">
                    <v-icon>mdi-brain</v-icon>
                </v-tab>
            </template>
        </v-tooltip>

        <v-tooltip text="Function calls done by the director" location="top">
            <template #activator="{ props }">
                    <v-tab v-bind="props" value="function_calls" :ripple="false" color="primary">
                    <v-icon>mdi-function</v-icon>
                </v-tab>
            </template>
        </v-tooltip>

        <v-tooltip text="Chat with the director" location="top">
            <template #activator="{ props }">
                <v-tab v-bind="props" value="chats" :ripple="false" color="primary">
                    <v-icon>mdi-chat</v-icon>
                </v-tab>
            </template>
        </v-tooltip>
    </v-tabs>
    
    <v-tabs-window v-model="activeTab">
        <v-tabs-window-item value="phase">
            <v-toolbar density="compact" flat color="mutedbg">
                <v-toolbar-title class="text-subtitle-2 text-muted"><v-icon class="mr-1">mdi-bullhorn</v-icon> Scene Direction</v-toolbar-title>
                <v-spacer></v-spacer>
                <v-btn @click="openWorldStateManager('scene','director')" color="primary" size="small">Manage</v-btn>
            </v-toolbar>
            <v-divider class="mb-2"></v-divider>
            <v-card>
                <v-card-text>
                    <v-select :items="sceneTypes" v-model="intent.phase.scene_type" label="Scene Type" class="text-caption" density="compact" @update:model-value="updateSceneIntent()"></v-select>
                    
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
                <v-card-actions></v-card-actions>
            </v-card>
        </v-tabs-window-item>

        <v-tabs-window-item value="actions">
            <v-toolbar density="compact" flat color="mutedbg">
                <v-toolbar-title class="text-subtitle-2 text-muted"><v-icon class="mr-1">mdi-brain</v-icon> Actions</v-toolbar-title>
                <v-chip size="x-small" color="primary" class="ml-2">Max. {{ max_messages }}</v-chip>
                <v-spacer></v-spacer>
                <v-btn color="delete" variant="text" size="small" @click="clearMessages" prepend-icon="mdi-close">Clear</v-btn>
            </v-toolbar>
            <v-divider class="mb-2"></v-divider>
            <v-slider density="compact" v-model="max_messages" min="1" hide-details max="50" step="1" color="primary" class="mx-4 mb-2"></v-slider>
            <div class="message-container">
                <director-console-message 
                    v-for="message in regularMessages" 
                    :key="message.id" 
                    :message="message" 
                />
                <div v-if="regularMessages.length === 0" class="text-caption text-muted pa-2">
                    No director messages yet
                </div>
            </div>
        </v-tabs-window-item>
        
        <v-tabs-window-item value="function_calls">
            <v-toolbar density="compact" flat color="mutedbg">
                <v-toolbar-title class="text-subtitle-2 text-muted"><v-icon class="mr-1">mdi-function</v-icon> Function Calls</v-toolbar-title>
                <v-spacer></v-spacer>
            </v-toolbar>
            <v-divider class="mb-2"></v-divider>
            <div class="message-container">
                <director-console-message 
                    v-for="message in functionCallMessages" 
                    :key="message.id" 
                    :message="message" 
                />
                <div v-if="functionCallMessages.length === 0" class="text-caption text-muted pa-2">
                    No function calls yet
                </div>
            </div>
        </v-tabs-window-item>

        <v-tabs-window-item value="chats">
            <DirectorConsoleChats :scene="scene" />
        </v-tabs-window-item>
    </v-tabs-window>

</template>

<script>
import DirectorConsoleMessage from './DirectorConsoleMessage.vue';
import ContextualGenerate from './ContextualGenerate.vue';
import DirectorConsoleChats from './DirectorConsoleChats.vue';

export default {
    name: 'DirectorConsole',
    components: {
        DirectorConsoleMessage,
        ContextualGenerate,
        DirectorConsoleChats,
    },
    props: {
        scene: Object,
        open: {
            type: Boolean,
            default: false,
        }
    },
    inject: [
        'openWorldStateManager',
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    watch: {
        open(newVal) {
            if(newVal) {
                this.getSceneIntent();
            }
        },
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
        regularMessages() {
            return this.messages.filter(message => message.subtype !== 'function_call');
        },
        functionCallMessages() {
            return this.messages.filter(message => message.subtype === 'function_call');
        },
        
    },
    data() {
        return {
            messages: [],
            max_messages: 20,
            activeTab: 'chats',
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
        }
    },
    methods: {
        clearMessages() {
            this.messages = [];
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

            if (message.action === 'get_scene_intent') {
                this.intent = message.data;
            }

            if(message.type != "director") {
                return;
            }

            if(message.character && !message.message) {
                // empty instruction (passing turn)
                return;
            }

            // Ignore chat protocol events in Actions tab
            const chatProtocolActions = ['chat_created', 'chat_history', 'chat_cleared', 'chat_append', 'chat_done'];
            if (chatProtocolActions.includes(message.action)) {
                return;
            }

            this.messages.unshift(message);
            
            // Keep messages within the max limit
            while(this.messages.length > this.max_messages) {
                this.messages.shift();
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>

<style scoped>
</style>
