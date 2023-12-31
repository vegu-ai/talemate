<template>
    <div v-if="isConnected()">
        <v-list v-for="(agent, index) in state.agents" :key="index">
            <v-list-item @click="editAgent(index)">
                <v-list-item-title>
                    <v-progress-circular v-if="agent.status === 'busy'" indeterminate color="primary"
                        size="14"></v-progress-circular>
                    <v-icon v-else-if="agent.status === 'uninitialized'" color="orange" size="14">mdi-checkbox-blank-circle</v-icon>
                    <v-icon v-else-if="agent.status === 'disabled'" color="grey-darken-2" size="14">mdi-checkbox-blank-circle</v-icon>
                    <v-icon v-else-if="agent.status === 'error'" color="red" size="14">mdi-checkbox-blank-circle</v-icon>
                    <v-icon v-else color="green" size="14">mdi-checkbox-blank-circle</v-icon>
                    <span class="ml-1" v-if="agent.label"> {{ agent.label }}</span>
                    <span class="ml-1" v-else> {{ agent.name }}</span>
                </v-list-item-title>
                <v-list-item-subtitle class="text-caption">
                    {{ agent.client }}
                </v-list-item-subtitle>
                <v-chip class="mr-1" v-if="agent.status === 'disabled'" size="x-small">Disabled</v-chip>
                <v-chip v-if="agent.data.experimental" color="warning" size="x-small">experimental</v-chip>
            </v-list-item>
        </v-list>
        <AgentModal :dialog="state.dialog" :formTitle="state.formTitle" @save="saveAgent" @update:dialog="updateDialog"></AgentModal>
    </div>
</template>
    
<script>
import AgentModal from './AgentModal.vue';

export default {
    components: {
        AgentModal
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
            }
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

            for(let i = 0; i < this.state.agents.length; i++) {
                let agent = this.state.agents[i];

                if(!agent.data.requires_llm_client)
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
        handleMessage(data) {
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
                    agent.actions = {}
                    for(let i in data.data.actions) {
                        agent.actions[i] = {enabled: data.data.actions[i].enabled, config: data.data.actions[i].config};
                    }
                    agent.enabled = data.data.enabled;
                } else {
                    // Add the agent to the list of agents
                    let actions = {}
                    for(let i in data.data.actions) {
                        actions[i] = {enabled: data.data.actions[i].enabled, config: data.data.actions[i].config};
                    }
                    this.state.agents.push({
                        name: data.name,
                        client: data.client,
                        status: data.status,
                        data: data.data,
                        label: data.message,
                        actions: actions,
                        enabled: data.data.enabled,
                    });
                    console.log("agents: added new agent", this.state.agents[this.state.agents.length - 1], data)
                }
                return;
            }
        }
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>