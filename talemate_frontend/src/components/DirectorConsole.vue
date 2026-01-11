<template>
    <v-toolbar density="compact" flat color="mutedbg">
        <v-toolbar-title class="text-muted">
            <v-icon size="small" color="secondary">mdi-bullhorn</v-icon> Director Console
        </v-toolbar-title>
        
        <v-menu>
            <template v-slot:activator="{ props }">
                <v-chip
                    v-bind="props"
                    size="small"
                    class="ml-2 mr-2"
                    :color="directorPersonaName ? 'persona' : 'default'"
                    label
                    clickable
                    :disabled="appBusy || !appReady"
                >
                    <v-icon start>mdi-drama-masks</v-icon>
                    {{ directorPersonaName || 'No Persona' }}
                    <v-icon end>mdi-chevron-down</v-icon>
                </v-chip>
            </template>
            <v-list density="compact">
                <v-list-item
                    v-for="template in directorPersonaTemplates"
                    :key="template.value"
                    @click="updateDirectorPersona(template.value)"
                    :active="currentDirectorPersona === template.value"
                >
                    <template v-slot:prepend>
                        <v-icon>{{ template.value ? 'mdi-drama-masks' : 'mdi-cancel' }}</v-icon>
                    </template>
                    <v-list-item-title>{{ template.title }}</v-list-item-title>
                </v-list-item>
                <v-divider></v-divider>
                <v-list-item @click="openPersonaManager">
                    <template v-slot:prepend>
                        <v-icon>mdi-cog</v-icon>
                    </template>
                    <v-list-item-title>Manage Personas</v-list-item-title>
                </v-list-item>
            </v-list>
        </v-menu>
    </v-toolbar>
    
    <v-divider></v-divider>

    <v-tabs v-model="activeTab" density="compact" align-tabs="center" color="secondary">
        <v-tooltip text="Scene Direction" location="top">
            <template #activator="{ props }">
                <v-tab v-bind="props" value="phase" :ripple="false">
                    <v-icon>mdi-bullhorn</v-icon>
                </v-tab>
            </template>
        </v-tooltip>

        <v-tooltip text="Chat with the director" location="top">
            <template #activator="{ props }">
                <v-tab v-bind="props" value="chats" :ripple="false">
                    <v-icon>mdi-chat</v-icon>
                </v-tab>
            </template>
        </v-tooltip>

        <v-tooltip text="Actions taken by the director" location="top">
            <template #activator="{ props }">
                <v-tab v-bind="props" value="actions" :ripple="false">
                    <v-icon>mdi-brain</v-icon>
                </v-tab>
            </template>
        </v-tooltip>

        <v-tooltip text="Function calls done by the director" location="top">
            <template #activator="{ props }">
                    <v-tab v-bind="props" value="function_calls" :ripple="false">
                    <v-icon>mdi-function</v-icon>
                </v-tab>
            </template>
        </v-tooltip>


    </v-tabs>
    
    <v-tabs-window v-model="activeTab">
        <v-tabs-window-item value="phase">
            <DirectorConsoleSceneDirection :scene="scene" :app-busy="appBusy" :app-ready="appReady" />
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
            <DirectorConsoleChats 
                :scene="scene" 
                :app-busy="appBusy" 
                :app-ready="appReady"
            />
        </v-tabs-window-item>
    </v-tabs-window>

</template>

<script>
import DirectorConsoleMessage from './DirectorConsoleMessage.vue';
import DirectorConsoleSceneDirection from './DirectorConsoleSceneDirection.vue';
import DirectorConsoleChats from './DirectorConsoleChats.vue';

export default {
    name: 'DirectorConsole',
    components: {
        DirectorConsoleMessage,
        DirectorConsoleSceneDirection,
        DirectorConsoleChats,
    },
    props: {
        scene: Object,
        open: {
            type: Boolean,
            default: false,
        },
        appBusy: {
            type: Boolean,
            default: false,
        },
        appReady: {
            type: Boolean,
            default: true,
        }
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'openWorldStateManager',
    ],
    computed: {
        regularMessages() {
            return this.messages.filter(message => message.subtype !== 'function_call');
        },
        functionCallMessages() {
            return this.messages.filter(message => message.subtype === 'function_call');
        },
        directorPersonaName() {
            const names = this.scene?.data?.agent_persona_names;
            const uid = this.scene?.data?.agent_persona_templates?.director;
            
            if(names?.director) return names.director;
            if(!uid) return null;
            
            const templates = this.scene?.templates?.by_type?.agent_persona || {};
            const tpl = templates[uid];
            console.debug('[DirectorConsole] persona template resolve', { found: !!tpl, tpl });
            return tpl?.name || null;
        },
        directorPersonaTemplates() {
            const agentPersonas = this.availableTemplates?.by_type?.agent_persona;
            
            if(!agentPersonas) {
                return [{ value: null, title: 'None' }];
            }
            
            const templates = Object.values(agentPersonas).map((template) => ({
                value: `${template.group}__${template.uid}`,
                title: template.name,
            }));
            
            templates.unshift({ value: null, title: 'None' });
            return templates;
        },
        currentDirectorPersona() {
            return this.scene?.data?.agent_persona_templates?.director || null;
        }
    },
    data() {
        return {
            messages: [],
            max_messages: 20,
            activeTab: 'chats',
            availableTemplates: {},
        }
    },
    methods: {
        clearMessages() {
            this.messages = [];
        },
        updateDirectorPersona(newPersona) {
            // Send persona update to backend - it will sync back via emit_status
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'update_persona',
                persona: newPersona,
            }));
        },
        openPersonaManager() {
            // Navigate to Templates tab (agent_persona filter could be added later if needed)
            this.openWorldStateManager('templates', 'agent_persona');
        },
        requestTemplates() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_templates',
            }));
        },
        handleMessage(message) {
            // Handle templates response from world_state_manager
            if(message.type === 'world_state_manager' && message.action === 'templates') {
                if(message.data && message.data.by_type) {
                    this.availableTemplates = { by_type: message.data.by_type };
                } else {
                    this.availableTemplates = message.data || {};
                }
                return;
            }
            
            if(message.type != "director") {
                return;
            }

            if(message.character && !message.message) {
                // empty instruction (passing turn)
                return;
            }

            // Ignore chat protocol events in Actions tab
            const chatProtocolActions = [
                'chat_created', 'chat_history', 'chat_cleared', 'chat_append', 'chat_done',
                'scene_direction_history', 'scene_direction_append', 'scene_direction_compacting'
            ];
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
        this.requestTemplates();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>

<style scoped>
</style>
