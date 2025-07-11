<template>
    <div v-if="isConnected()">
        <v-list density="compact">
            <v-list-item  v-for="(agent, index) in state.agents" :key="index" @click="editAgent(index)">
                <v-list-item-title>
                    <v-progress-circular v-if="agent.status === 'busy'" indeterminate="disable-shrink" color="primary"
                        size="14"></v-progress-circular>
                    <v-progress-circular v-else-if="agent.status === 'busy_bg'" indeterminate="disable-shrink" color="secondary"
                        size="14"></v-progress-circular>
                    <v-icon v-else-if="agent.status === 'uninitialized'" color="orange" size="14">mdi-checkbox-blank-circle</v-icon>
                    <v-icon v-else-if="agent.status === 'disabled'" color="grey-darken-2" size="14">mdi-checkbox-blank-circle</v-icon>
                    <v-icon v-else-if="agent.status === 'error'" color="red-darken-1" size="14">mdi-checkbox-blank-circle</v-icon>
                    <v-icon v-else color="green" size="14">mdi-checkbox-blank-circle</v-icon>

                    <span class="ml-1" v-if="agent.label"> {{ agent.label }}</span>
                    <span class="ml-1" v-else> {{ agent.name }}</span>
                    <v-tooltip v-if="agent.data.experimental" text="Experimental" density="compact">
                        <template v-slot:activator="{ props }">
                            <v-icon v-bind="props" color="warning" size="14" class="ml-1">mdi-flask-outline</v-icon>
                        </template>
                    </v-tooltip>
                    <AgentMessages v-if="agentHasMessages[agent.name]" :messages="messages[agent.name] || []" :agent="agent.name" :messageReceiveTime="agentHasMessages[agent.name]" />

                </v-list-item-title>
                
                <div class="d-flex flex-wrap align-center chip-container">
                    <!-- Client chip for string type -->
                    <v-chip v-if="typeof(agent.client) === 'string'" 
                        prepend-icon="mdi-network-outline" 
                        size="x-small" 
                        color="grey" 
                        variant="tonal" 
                        label>
                        {{ agent.client }}
                    </v-chip>

                    <!-- Client chips for object type -->
                    <template v-else-if="typeof(agent.client) === 'object'">
                        <v-tooltip v-for="(detail, key) in agent.client" :key="key" :text="detail.description" >
                            <template v-slot:activator="{ props }">
                                <v-chip 
                                size="x-small" 
                                v-bind="props"
                                :prepend-icon="detail.icon"
                                label
                                :color="detail.color || 'grey'"
                                variant="tonal"
                                >
                                {{ detail.value }}
                                </v-chip>
                            </template>
                        </v-tooltip>
                    </template>

                    <div v-if="agentStateNotifications[agent.name]">
                        <v-tooltip v-for="(state, key) in agentStateNotifications[agent.name]" :key="key" :text="state.value" >
                            <template v-slot:activator="{ props }">
                                <v-chip v-bind="props" size="x-small" label variant="tonal" :color="state.color || 'highlight5'" prepend-icon="mdi-bell-outline">
                                    {{ state.key }}
                                </v-chip>
                            </template>
                        </v-tooltip>
                    </div>

                    <!-- Quick toggle action chips with their sub-config chips -->
                    <template v-for="(action, action_name) in agent.actions" :key="action_name">
                        <!-- Action chip (if it has quick_toggle) -->
                        <template v-if="action.quick_toggle">
                            <v-chip 
                                size="x-small" 
                                label
                                :color="action.enabled ? 'success' : 'grey'"
                                variant="tonal"
                                :prepend-icon="action.icon"
                                @click.stop="toggleAction(agent, action_name, action)"
                            >
                                {{ action.label }}
                                <v-icon class="ml-1" size="small" v-if="action.enabled">mdi-check-circle-outline</v-icon>
                                <v-icon class="ml-1" size="small" v-else>mdi-circle-outline</v-icon>
                            </v-chip>
                        </template>
                        <!-- Related sub-config chips (if action is enabled) -->
                        <template v-if="action.enabled && action.config">
                            <v-chip 
                                v-for="(config, config_name) in getQuickToggleSubConfigs(action)" 
                                :key="`${action_name}-${config_name}`"
                                size="x-small" 
                                label
                                :color="config.value ? 'highlight3' : 'grey'"
                                variant="tonal"
                                @click.stop="toggleSubConfig(agent, action_name, config_name, config)"
                            >
                                {{ config.label }}
                                <v-icon class="ml-1" size="x-small" v-if="config.value">mdi-check-circle-outline</v-icon>
                                <v-icon class="ml-1" size="x-small" v-else>mdi-circle-outline</v-icon>
                            </v-chip>
                        </template>
                    </template>
                </div>
            </v-list-item>
        </v-list>
        <AgentModal :dialog="state.dialog" :formTitle="state.formTitle" @save="saveAgent" @update:dialog="updateDialog" ref="modal"></AgentModal>
    </div>
</template>
    
<script>
import AgentModal from './AgentModal.vue';
import AgentMessages from './AgentMessages.vue';

export default {
    components: {
        AgentModal,
        AgentMessages
    },

    data() {
        return {
            state: {
                agents: [],
                dialog: false,
                currentAgent: {
                    type: '',
                    client: '',
                    status: 'idle',
                    label: '',
                    name: '',
                    data: {},
                },
                formTitle: ''
            },
            maxMessagesPerAgent: 25,
            agentHasMessages: {},
            messages: {},
        }
    },
    props: {
        agentState: {
            type: Object,
            default: () => ({})
        }
    },
    computed: {
        agentStateNotifications() {
            // if key begins with 'notify__' and value is a string, return the key and value
            // return the notify__(.+) part as the key, and the value as the value
            // the key will also be title-ized (title and space instead of underscore)

            // this is done per agent, so we need to iterate over the agents and return a dict
            // with the agent name as the key and the notifications as the value (a list of dicts)
            let notifications = {};
            for(let agent in this.agentState) {
                notifications[agent] = Object.keys(this.agentState[agent]).filter(key => key.startsWith('notify__') && typeof this.agentState[agent][key] === 'string').map(key => {
                    return {
                        key: key.replace('notify__', '').replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase()),
                        value: this.agentState[agent][key]
                    }
                });
            }
            console.log("agentStateNotifications", notifications);
            return notifications;
        }
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'isConnected',
        'getClients',
    ],
    provide() {
        return {
            state: this.state
        };
    },
    methods: {
        configurationRequired() {
            let clients = this.getClients();

            const agentErrors = [];

            for(let i = 0; i < this.state.agents.length; i++) {
                let agent = this.state.agents[i];

                // any agent erroring should be explicitly returned
                if(agent.status === 'error') {
                    return true;
                }

                if(!agent.data.requires_llm_client || agent.meta.essential === false)
                    continue

                if(agent.status === 'warning' || agent.status === 'error' || agent.status === 'uninitialized') {
                    console.log("agents: configuration required (1)", agent.status)
                    return true;
                }

                // loop through all clients until we find the client assigned
                // to the agent, then check the client status to see if it's ok
                for(let j = 0; j < clients.length; j++) {
                    let client = clients[j];
                    if(client.name === agent.client) {
                        if(client.status === 'warning' || client.status === 'error' || client.status === 'disabled') {
                            console.log("agents: configuration required (2)", client.status)
                            return true;
                        }
                    }
                }
            }

            return false;
        },
        toggleAction(agent, action_name, action) {
            // Toggle the action's enabled state
            action.enabled = !action.enabled;
            
            // Update the agent's actions
            agent.actions[action_name].enabled = action.enabled;
            
            // Save the agent to persist the changes
            this.saveAgent(agent);
            
            // Send update to server
            this.getWebsocket().send(JSON.stringify({
                type: 'agent_action',
                agent_name: agent.name,
                action_name: action_name,
                enabled: action.enabled
            }));
        },
        toggleSubConfig(agent, action_name, config_name, config) {
            // Toggle the config value (assuming it's a boolean)
            config.value = !config.value;
            
            // Update the agent's config
            agent.actions[action_name].config[config_name].value = config.value;
            
            // Save the agent to persist the changes
            this.saveAgent(agent);
            
            // Send update to server using the same type as action toggles
            this.getWebsocket().send(JSON.stringify({
                type: 'agent_action',
                agent_name: agent.name,
                action_name: action_name,
                config: {
                    [config_name]: config.value
                }
            }));
        },
        getQuickToggleActions(agent) {
            const result = {};
            if (agent.actions) {
                for (const action_name in agent.actions) {
                    if (agent.actions[action_name] && agent.actions[action_name].quick_toggle) {
                        result[action_name] = agent.actions[action_name];
                    }
                }
            }
            return result;
        },
        getQuickToggleSubConfigs(action) {
            const result = {};
            if (action.config) {
                for (const config_name in action.config) {
                    if (action.config[config_name] && action.config[config_name].quick_toggle) {
                        result[config_name] = action.config[config_name];
                    }
                }
            }
            return result;
        },
        getActive() {
            return this.state.agents.find(a => a.status === 'busy');
        },
        openModal() {
            this.state.formTitle = 'Add AI Agent';
            this.state.dialog = true;
        },
        saveAgent(agent) {
            const index = this.state.agents.findIndex(c => c.name === agent.name);
            if (index === -1) {
                this.state.agents.push(agent);
            } else {
                this.state.agents[index] = agent;
            }
            this.$emit('agents-updated', this.state.agents);
        },
        editAgent(index) {
            this.state.currentAgent = { ...this.state.agents[index] };
            this.state.formTitle = 'Edit AI Agent';
            this.state.dialog = true;
        },
        deleteAgent(index) {
            if (window.confirm('Are you sure you want to delete this agent?')) {
                this.state.agents.splice(index, 1);
                this.$emit('agents-updated', this.state.agents);
            }
        },
        updateDialog(newVal) {
            this.state.dialog = newVal;
        },
        openSettings(agentName, section) {
            let index = this.state.agents.findIndex(a => a.name === agentName);
            if (index !== -1) {
                this.editAgent(index);
                if(section)
                    this.$refs.modal.tab = section;
            }
        },
        handleMessage(data) {

            // When a new scene is loaded, clear the messages and agentHasMessages
            if (data.type === "system" && data.id === 'scene.loaded') {
                this.messages = {};
                this.agentHasMessages = {};
            }

            // Handle agent_status message type
            if (data.type === 'agent_status') {
                // Find the client with the given name
                const agent = this.state.agents.find(agent => agent.name === data.name);
                if (agent) {

                    // Update the model name of the client
                    agent.client = data.client;
                    agent.data = data.data;
                    agent.status = data.status;
                    agent.label = data.message;
                    agent.meta = data.meta;
                    agent.actions = {}
                    for(let i in data.data.actions) {
                        agent.actions[i] = {...data.data.actions[i]};
                    }
                    agent.enabled = data.data.enabled;

                    // sort agents by label

                    this.state.agents.sort((a, b) => {
                        if(a.label < b.label) { return -1; }
                        if(a.label > b.label) { return 1; }
                        return 0;
                    });

                } else {
                    // Add the agent to the list of agents
                    let actions = {}
                    for(let i in data.data.actions) {
                        //actions[i] = {enabled: data.data.actions[i].enabled, config: data.data.actions[i].config, condition: data.data.actions[i].condition};
                        actions[i] = {...data.data.actions[i]};
                    }
                    this.state.agents.push({
                        name: data.name,
                        client: data.client,
                        status: data.status,
                        data: data.data,
                        label: data.message,
                        actions: actions,
                        enabled: data.data.enabled,
                        meta: data.meta,
                    });
                    console.log("agents: added new agent", this.state.agents[this.state.agents.length - 1], data)
                }
                return;
            }

            if (data.type === 'agent_message') {
                const agent = data.data.agent;
                if (!this.messages[agent]) {
                    this.messages[agent] = [];
                }
                this.messages[agent].unshift(data);
                while (this.messages[agent].length > this.maxMessagesPerAgent) {
                    this.messages[agent].pop();
                }
                // set to current time in milliseconds
                this.agentHasMessages[agent] = Date.now();
            }
        }
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped>
.chip-wrapper {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    max-width: 100%;
    margin-top: 4px;
}

.chip-container {
    gap: 4px;
}
</style>