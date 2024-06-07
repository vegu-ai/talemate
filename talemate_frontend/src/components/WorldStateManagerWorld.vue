<template>
    <v-card>
        <v-card-text>
            <v-tabs-window v-model="tab">
                <v-tabs-window-item value="entries">
                    <WorldStateManagerWorldEntries ref="entries" 
                    :immutable-entries="entries"
                    :templates="templates" 
                    :generation-options="generationOptions" />
                </v-tabs-window-item>
                <v-tabs-window-item value="states">
                    <WorldStateManagerWorldStates ref="states"
                    :templates="templates"
                    :immutable-states="states"
                    :generation-options="generationOptions" />
                </v-tabs-window-item>
                <v-tabs-window-item value="info">
                    <v-alert type="info" color="grey" variant="text" icon="mdi-earth">
                        Add world information / lore and additional details.
                        <br><br>
                        You can also set up automatic reinforcement of world information states. This will cause the AI to regularly re-evaluate the state and update the detail accordingly.
                        <br><br>
                        Add a new entry or select an existing one to get started.
                        <br><br>
                        <v-icon color="orange" class="mr-1">mdi-alert</v-icon> If you want to add details to an acting character do that through the character manager instead.
                    </v-alert>
                </v-tabs-window-item>
            </v-tabs-window>
        </v-card-text>
    </v-card>
</template>

<script>

import WorldStateManagerWorldStates from './WorldStateManagerWorldStates.vue';
import WorldStateManagerWorldEntries from './WorldStateManagerWorldEntries.vue';

export default {
    name: 'WorldStateManagerWorld',
    components: {
        WorldStateManagerWorldStates,
        WorldStateManagerWorldEntries,
    },
    props: {
        templates: Object,
        generationOptions: Object,
        entries: Object,
        states: Object,
    },
    data() {
        return {
            tab: 'info',
        }
    },
    methods: {
        navigate(selection) {
            if(selection === '$NEW_ENTRY') {
                this.tab = 'entries';
                this.$nextTick(() => {
                    this.$refs.entries.create();
                });
            } else if(selection === '$NEW_STATE') {
                this.tab = 'states';
                this.$nextTick(() => {
                    this.$refs.states.create();
                });
            } else {
                // if selection starts with 'entry:' or 'state:' then split it and navigate to the correct tab
                let parts = selection.split(':');
                if(parts[0] === 'entry') {
                    this.tab = 'entries';
                    this.$nextTick(() => {
                        this.$refs.entries.select(parts[1]);
                    });
                } else if(parts[0] === 'state') {
                    this.tab = 'states';
                    this.$nextTick(() => {
                        this.$refs.states.select(parts[1]);
                    });
                } else {
                    this.tab = 'info';
                }

            }
        }
    }
}

</script>