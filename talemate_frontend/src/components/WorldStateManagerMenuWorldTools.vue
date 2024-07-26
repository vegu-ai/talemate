<template>

    <v-list density="compact" slim>
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-plus</v-icon>
            Create
        </v-list-subheader>
        <v-list-item prepend-icon="mdi-text-box-plus" @click.stop="createNewEntry">
            <v-list-item-title>New Entry</v-list-item-title>
            <v-list-item-subtitle class="text-caption">Information and details.</v-list-item-subtitle>
        </v-list-item>
        <v-list-item prepend-icon="mdi-image-auto-adjust" @click.stop="createNewState">
            <v-list-item-title>New State Reinforcement</v-list-item-title>
            <v-list-item-subtitle class="text-caption">Automatically tracked state</v-list-item-subtitle>
        </v-list-item>
        <v-list-item>
            <v-text-field class="mt-1" variant="underlined" v-model="filter" label="Filter" density="compact"></v-text-field>
        </v-list-item>
    </v-list>

    <v-list selectable slim density="compact" v-model:opened="groupsOpen" color="secondary" v-model:selected="selected">

        <v-list-group fluid value="entries" color="primary">
            <template v-slot:activator="{ props }">
                <v-list-item v-bind="props">
                    <v-list-item-title>Entries ({{ entriesNumber }})</v-list-item-title>
                </v-list-item>
            </template>
            <v-list-item v-for="(entry, key) in filteredEntries" :key="key" :value="`entry:${entry.id}`" prepend-icon="mdi-text-box-outline">
                <v-list-item-title>{{ entry.id }}</v-list-item-title>
                <v-list-item-subtitle>{{ entry.text }}</v-list-item-subtitle>
            </v-list-item>
            <v-card v-if="entries.length == 0" class="ma-2 text-muted">
                <v-card-text>No entries</v-card-text>
            </v-card>
        </v-list-group>

        <v-list-group fluid value="reinforcements" color="primary">
            <template v-slot:activator="{ props }">
                <v-list-item v-bind="props">
                    <v-list-item-title>States ({{ reinforcementsNumber }})</v-list-item-title>
                </v-list-item>
            </template>
            <v-list-item v-for="(reinforcement, key) in filteredReinforcements" :key="key" :value="`state:${reinforcement.question}`" prepend-icon="mdi-text-box-outline">
                <v-list-item-title>{{ reinforcement.question }}</v-list-item-title>
                <v-list-item-subtitle>{{ reinforcement.text }}</v-list-item-subtitle>
            </v-list-item>
            <v-card v-if="reinforcements.length == 0" class="ma-2 text-muted">
                <v-card-text>No reinforcements</v-card-text>
            </v-card>
        </v-list-group>

    </v-list>

</template>
<script>

export default {
    name: 'WorldStateManagerMenuWorldTools',
    props: {
        scene: Object,
        manager: Object,
        worldStateTemplates: Object,
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    data() {
        return {
            selected: null,
            groupsOpen: ['entries', 'reinforcements'],
            entries: {},
            reinforcements: {},
            filter: '',
        }
    },
    watch: {
        selected: {
            immediate: true,
            handler(selected) {
                console.log('selected', selected);
                if (selected) {
                    this.load(selected[0]);
                }
            }
        }
    },
    computed: {
        filteredEntries() {
            return Object.values(this.entries).filter(entry => entry.id.toLowerCase().includes(this.filter.toLowerCase()));
        },
        filteredReinforcements() {
            return Object.values(this.reinforcements).filter(reinforcement => reinforcement.question.toLowerCase().includes(this.filter.toLowerCase()));
        },
        entriesNumber() {
            return Object.keys(this.entries).length;
        },
        reinforcementsNumber() {
            return Object.keys(this.reinforcements).length;
        },
    },
    emits: [
        'world-state-manager-navigate'
    ],
    methods: {
        reset() {
            this.selected = null;
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action == 'world') {
                this.entries = message.data.entries;
                this.reinforcements = message.data.reinforcements;
                console.log('entries', this.entries);
                console.log('reinforcements', this.reinforcements);
            }
        },
        load(id) {
            this.$emit('world-state-manager-navigate', 'world', id);
        },
        createNewEntry() {
            this.$emit('world-state-manager-navigate', 'world', '$NEW_ENTRY');
            this.selected = [];
        },
        createNewState() {
            this.$emit('world-state-manager-navigate', 'world', '$NEW_STATE');
            this.selected = [];
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