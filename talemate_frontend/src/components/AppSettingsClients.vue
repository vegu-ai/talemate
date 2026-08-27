<template>
    <v-row>
        <v-col cols="4">
            <v-alert v-if="clientNames.length === 0" type="warning" variant="tonal" density="compact" class="mb-2">
                You have no LLM clients configured. Add one.
            </v-alert>
            <v-list slim selectable mandatory v-model:selected="selected" color="primary" density="compact">
                <v-list-item v-for="name in clientNames" :key="name" :value="name">
                    <template v-slot:prepend>
                        <v-progress-circular v-if="statusOf(name) === 'busy'" indeterminate="disable-shrink" color="primary" size="14" class="mr-3"></v-progress-circular>
                        <v-icon v-else :color="statusColor(name)" size="14" class="mr-3">mdi-checkbox-blank-circle</v-icon>
                    </template>
                    <v-list-item-title>{{ name }}</v-list-item-title>
                    <v-list-item-subtitle class="text-caption">
                        {{ typeTitle(config.clients[name].type) }}
                        <span v-if="modelHint(name)" class="text-muted"> — {{ modelHint(name) }}</span>
                    </v-list-item-subtitle>
                    <template v-slot:append>
                        <v-chip v-if="!liveStatus[name]" size="x-small" label color="warning" variant="text">Unsaved</v-chip>
                    </template>
                </v-list-item>
            </v-list>

            <v-menu v-model="typeMenu" :close-on-content-click="false">
                <template v-slot:activator="{ props }">
                    <v-btn v-bind="props" variant="text" color="primary" prepend-icon="mdi-plus-box" class="mt-2"
                        :disabled="typeChoices.length === 0" data-setting-anchor="add-client">Add client</v-btn>
                </template>
                <v-list density="compact" max-height="480">
                    <v-list-subheader>Client type</v-list-subheader>
                    <v-list-item v-for="choice in typeChoices" :key="choice.value" @click="addClient(choice.value)">
                        <v-list-item-title>{{ choice.title }}</v-list-item-title>
                        <template v-slot:append>
                            <v-icon v-if="choice.experimental" color="warning" size="x-small">mdi-flask</v-icon>
                        </template>
                    </v-list-item>
                </v-list>
            </v-menu>

            <v-divider class="mt-4 mb-2"></v-divider>

            <v-switch v-model="paramPanelEnabled" density="compact" color="primary" hide-details
                data-setting-anchor="inference-param-panel" label="Inference parameter panel">
                <v-tooltip activator="parent" location="bottom" max-width="400">Lets a client's inference parameters be pinned to a panel beside the client list, where they are edited during play. Pick the client in the preset menu on its entry in that list.</v-tooltip>
            </v-switch>
        </v-col>

        <v-col cols="8">
            <div v-if="selectedClient">
                <div class="d-flex align-center mb-2">
                    <v-icon class="mr-2" color="primary">mdi-network-outline</v-icon>
                    <span class="text-subtitle-1">{{ selectedName }}</span>
                    <v-spacer></v-spacer>
                    <v-btn variant="text" size="small" color="primary" prepend-icon="mdi-transit-connection-variant"
                        :disabled="selectedClient.enabled === false"
                        data-setting-anchor="assign-to-all-agents" @click="assignToAllAgents">Assign to all agents
                        <v-tooltip activator="parent" location="bottom" max-width="400">Make every agent that generates with an LLM client use this client. Applied when you save.</v-tooltip>
                    </v-btn>
                    <v-btn variant="text" size="small" color="delete" prepend-icon="mdi-close-circle-outline"
                        @click="$refs.confirmDelete.initiateAction({client: selectedName})">Remove</v-btn>
                </div>
                <ClientConfigEditor
                    :client="selectedClient"
                    :meta="selectedMeta"
                    :config="config"
                    :status="liveStatus[selectedName] || null"
                    :validate-name="validateClientName"
                    @rename="renameClient"
                />
            </div>
            <v-alert v-else class="text-medium-emphasis" variant="text">Select a client to configure</v-alert>
        </v-col>
    </v-row>

    <ConfirmActionPrompt ref="confirmDelete" @confirm="deleteClient" actionLabel="Remove client" icon="mdi-close-circle-outline" confirmText="Remove" cancelText="Cancel" :maxWidth="400" description="Remove the client {client}? It will be disconnected and purged when you save." />
</template>

<script>
import ClientConfigEditor from './ClientConfigEditor.vue';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import { buildClientFromDefaults } from '@/utils/clientPresets';
import { agentsRequiringClient } from '@/utils/agentAssignments';
import { cloneNameKeyedMap, hasOwnName, isReservedName } from '@/utils/nameKeyedMap';
import { movePinnedPanelClient, panelSettings } from '@/utils/inferencePresets';

// Clients page — master / detail management of `config.clients` in the app
// settings working copy.
//
// Everything on this page is working-copy state: adding, removing and editing
// clients only mutate `config.clients` (a name -> client map) and reach the
// backend through the settings toolbar's Save, where deletion-by-omission
// applies. Live client status is read-only decoration (status dot, model
// hint) and never feeds back into the working copy.
export default {
    name: 'AppSettingsClients',
    components: {
        ClientConfigEditor,
        ConfirmActionPrompt,
    },
    props: {
        config: Object,
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'getClients', 'getAgents'],
    data() {
        return {
            selected: [],
            // Meta().model_dump() per client type, from the client_types message
            clientTypes: {},
            // last known client_status per client name
            liveStatus: Object.create(null),
            typeMenu: false,
        }
    },
    computed: {
        paramPanelEnabled: {
            get() {
                return panelSettings(this.config?.presets).enabled;
            },
            set(value) {
                this.config.presets.inference_param_panel.enabled = value;
            },
        },
        clientNames() {
            return Object.keys(this.config?.clients || {}).sort((a, b) => a.localeCompare(b));
        },
        selectedName() {
            return this.selected.length ? this.selected[0] : null;
        },
        selectedClient() {
            if (!this.selectedName || !this.hasClient(this.selectedName)) {
                return null;
            }
            return this.config.clients[this.selectedName];
        },
        selectedMeta() {
            if (!this.selectedClient) {
                return {};
            }
            return this.clientTypes[this.selectedClient.type] || { defaults: {} };
        },
        typeChoices() {
            return Object.entries(this.clientTypes)
                .map(([value, meta]) => ({
                    value: value,
                    title: meta.title || value,
                    experimental: !!meta.experimental,
                }))
                .sort((a, b) => a.title.localeCompare(b.title));
        },
    },
    watch: {
        clientNames: {
            immediate: true,
            handler(names) {
                // live status is keyed by name — drop entries for names the
                // working copy no longer carries (removed or renamed), so a
                // re-added name doesn't inherit the previous client's status
                for (const name of Object.keys(this.liveStatus)) {
                    if (!names.includes(name)) {
                        delete this.liveStatus[name];
                    }
                }
                if (this.selectedName && names.includes(this.selectedName)) {
                    return;
                }
                this.selected = names.length ? [names[0]] : [];
            },
        },
    },
    methods: {
        hasClient(name) {
            return hasOwnName(this.config?.clients, name);
        },

        // save-time validation contract of the settings pages — AppSettings
        // asks every page that implements it before sending the config
        validate() {
            for (const [key, client] of Object.entries(this.config?.clients || {})) {
                const name = (client.name || '').trim();
                let error = null;
                if (!name || name !== key) {
                    error = `Client "${key}" needs a name.`;
                } else if (!Number.isFinite(Number(client.max_token_length)) || Number(client.max_token_length) <= 0) {
                    error = `Client "${key}": context length must be a positive number.`;
                }
                if (error) {
                    this.selected = [key];
                    return { valid: false, error: error };
                }
            }
            return { valid: true, error: null };
        },

        // what this page shows, folded into the settings view's UX snapshot
        // for the help agent
        uxSnapshot() {
            return { client: this.selectedName };
        },

        // deep link target — `navigate('clients', anchor, {client: name})`,
        // or `{action: 'add'}` to open the client type picker
        setSelection(item) {
            if (item && item.action === 'add') {
                this.typeMenu = true;
                return;
            }
            const name = typeof item === 'string' ? item : item?.client;
            if (!name || !this.hasClient(name)) {
                return;
            }
            this.selected = [name];
        },

        typeTitle(type) {
            return this.clientTypes[type]?.title || type;
        },

        statusOf(name) {
            return this.liveStatus[name]?.status || null;
        },

        statusColor(name) {
            switch (this.statusOf(name)) {
                case 'warning': return 'warning';
                case 'error': return 'delete';
                case 'disabled': return 'muted';
                case null: return 'muted';
                default: return 'success';
            }
        },

        modelHint(name) {
            const status = this.liveStatus[name];
            if (!status) {
                return null;
            }
            return status.data?.error_message || status.model_name || null;
        },

        validateClientName(value) {
            const name = (value || '').trim();
            if (!name) {
                return 'Client name is required.';
            }
            if (name !== this.selectedName && this.hasClient(name)) {
                return 'Client name already exists.';
            }
            if (isReservedName(name)) {
                return `"${name}" is reserved and cannot be used as a client name.`;
            }
            return true;
        },

        // seeds a new working copy entry from the client type's defaults; the
        // backend model supplies every field the defaults leave out
        addClient(type) {
            const meta = this.clientTypes[type];
            if (!meta) {
                return;
            }
            this.typeMenu = false;
            if (!this.config.clients) {
                this.config.clients = {};
            }
            const client = buildClientFromDefaults(meta, type, Object.keys(this.config.clients));
            this.config.clients[client.name] = client;
            this.selected = [client.name];
        },

        // Mirrors the drawer's per-client "assign to all agents" action, but
        // as a working-copy edit: the assignments become dirty state and reach
        // the backend through the toolbar Save like every other change here.
        assignToAllAgents() {
            const name = this.selectedName;
            if (!name) {
                return;
            }
            if (!this.config.agents) {
                this.config.agents = {};
            }
            for (const agent of agentsRequiringClient(this.getAgents())) {
                this.config.agents[agent.name] = {
                    // an agent the user has never configured has no entry to
                    // preserve — carry its live enabled state so the save
                    // doesn't silently re-enable a disabled agent
                    enabled: agent.enabled,
                    ...(this.config.agents[agent.name] || {}),
                    client: name,
                };
            }
        },

        // Agents reference their client by name, so removing or renaming one
        // has to carry through to `config.agents[*].client` in the same
        // working copy — otherwise the save would ship dangling references.
        // Clearing (rather than dropping the agent entry) matches the
        // backend's `ensure_agent_llm_client` fallback: an agent without a
        // client gets one assigned on apply.
        reassignAgents(oldName, newName) {
            for (const agent of Object.values(this.config?.agents || {})) {
                if (agent && agent.client === oldName) {
                    agent.client = newName;
                }
            }
        },

        deleteClient(params) {
            delete this.config.clients[params.client];
            this.reassignAgents(params.client, null);
            movePinnedPanelClient(this.config.presets, params.client, null);
        },

        // the client map is keyed by name, so a rename rebuilds the map (and
        // keeps `name` on the client itself in sync with its key)
        renameClient(newName) {
            const oldName = this.selectedName;
            if (!oldName || this.validateClientName(newName) !== true) {
                return;
            }
            // rebuilt in place rather than cloned and re-keyed, so the renamed
            // client keeps its position in the map
            const rebuilt = Object.create(null);
            for (const [key, client] of Object.entries(this.config.clients)) {
                if (key === oldName) {
                    client.name = newName;
                }
                rebuilt[key === oldName ? newName : key] = client;
            }
            this.config.clients = rebuilt;
            this.reassignAgents(oldName, newName);
            movePinnedPanelClient(this.config.presets, oldName, newName);
            this.selected = [newName];
        },

        requestClientTypes() {
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'request_client_types',
                data: {},
            }));
        },

        handleMessage(message) {
            if (message.type === 'client_status') {
                if (!this.hasClient(message.name)) {
                    // status for a client the working copy doesn't (or no
                    // longer) knows about — the backend still emits for
                    // clients pending purge
                    return;
                }
                this.liveStatus[message.name] = {
                    name: message.name,
                    type: message.message,
                    status: message.status,
                    model_name: message.model_name,
                    max_token_length: message.max_token_length,
                    api_url: message.api_url,
                    data: message.data,
                };
                return;
            }
            if (message.type === 'config' && message.action === 'client_types') {
                this.clientTypes = message.data;
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
        this.requestClientTypes();
        // the client list has been collecting status messages since the app
        // connected — adopt what it already knows instead of waiting for the
        // next status broadcast
        for (const client of this.getClients()) {
            if (this.hasClient(client.name)) {
                this.liveStatus[client.name] = client;
            }
        }
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>
