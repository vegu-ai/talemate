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
        <v-list-item>
            <div class="px-2">
                <div class="text-caption text-medium-emphasis mb-1">Show max.: {{ maxEntriesDisplay }}</div>
                <v-slider 
                    v-model="maxEntriesDisplay" 
                    :min="10" 
                    :max="300" 
                    :step="10"
                    density="compact"
                    hide-details
                    thumb-label
                    color="primary"
                ></v-slider>
            </div>
        </v-list-item>
    </v-list>

    <v-list selectable slim density="compact" v-model:opened="groupsOpen" color="secondary" v-model:selected="selected">

        <v-list-group fluid value="entries" color="primary">
            <template v-slot:activator="{ props }">
                <v-list-item v-bind="props">
                    <v-list-item-title>Entries ({{ displayedEntriesCount }} of {{ totalEntriesCount }})</v-list-item-title>
                </v-list-item>
            </template>
            <v-list-item v-for="entry in displayedEntries" :key="`entry-${entry.id}`" :value="`entry:${entry.id}`" prepend-icon="mdi-text-box-outline">
                <v-list-item-title>{{ entry.id }}</v-list-item-title>
                <v-list-item-subtitle>{{ entry.text }}</v-list-item-subtitle>
            </v-list-item>
            <v-card v-if="totalEntriesCount == 0" class="ma-2 text-muted">
                <v-card-text>No entries</v-card-text>
            </v-card>
        </v-list-group>

        <v-list-group fluid value="reinforcements" color="primary">
            <template v-slot:activator="{ props }">
                <v-list-item v-bind="props">
                    <v-list-item-title>States ({{ displayedReinforcementsCount }} of {{ totalReinforcementsCount }})</v-list-item-title>
                </v-list-item>
            </template>
            <v-list-item v-for="reinforcement in displayedReinforcements" :key="`state-${reinforcement.question}`" :value="`state:${reinforcement.question}`" prepend-icon="mdi-text-box-outline">
                <v-list-item-title>{{ reinforcement.question }}</v-list-item-title>
                <v-list-item-subtitle>{{ reinforcement.text }}</v-list-item-subtitle>
            </v-list-item>
            <v-card v-if="totalReinforcementsCount == 0" class="ma-2 text-muted">
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
            maxEntriesDisplay: 50,
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
            if (!this.filter) {
                return Object.values(this.entries);
            }
            const filterLower = this.filter.toLowerCase();
            return Object.values(this.entries).filter(entry => 
                entry.id.toLowerCase().includes(filterLower) || 
                (entry.text && entry.text.toLowerCase().includes(filterLower))
            );
        },
        displayedEntries() {
            return this.filteredEntries.slice(0, this.maxEntriesDisplay);
        },
        displayedEntriesCount() {
            return this.displayedEntries.length;
        },
        totalEntriesCount() {
            return this.filteredEntries.length;
        },
        filteredReinforcements() {
            if (!this.filter) {
                return Object.values(this.reinforcements);
            }
            const filterLower = this.filter.toLowerCase();
            return Object.values(this.reinforcements).filter(reinforcement => 
                reinforcement.question.toLowerCase().includes(filterLower) ||
                (reinforcement.answer && reinforcement.answer.toLowerCase().includes(filterLower)) ||
                (reinforcement.text && reinforcement.text.toLowerCase().includes(filterLower))
            );
        },
        displayedReinforcements() {
            return this.filteredReinforcements.slice(0, this.maxEntriesDisplay);
        },
        displayedReinforcementsCount() {
            return this.displayedReinforcements.length;
        },
        totalReinforcementsCount() {
            return this.filteredReinforcements.length;
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