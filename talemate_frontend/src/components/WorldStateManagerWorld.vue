<template>
    <div :style="{ maxWidth: MAX_CONTENT_WIDTH }">
    <v-card>
        <v-card-text>
            <v-tabs-window v-model="tab">
                <v-tabs-window-item value="entries">
                    <WorldStateManagerWorldEntries ref="entries" 

                    @load-pin="(ev, pin) => $emit('load-pin', ev, pin)"
                    @add-pin="(ev, pin) => $emit('add-pin', ev, pin)"

                    :immutable-entries="entries"
                    :templates="templates" 
                    :pins="pins"
                    :generation-options="generationOptions" />
                </v-tabs-window-item>
                <v-tabs-window-item value="states">
                    <WorldStateManagerWorldStates ref="states"
                    :templates="templates"
                    :immutable-states="states"
                    :pins="pins"
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
    </div>
</template>

<script>

import WorldStateManagerWorldStates from './WorldStateManagerWorldStates.vue';
import WorldStateManagerWorldEntries from './WorldStateManagerWorldEntries.vue';
import { MAX_CONTENT_WIDTH } from '@/constants';

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
        pins: Object,
    },
    data() {
        return {
            tab: 'info',
            MAX_CONTENT_WIDTH,
        }
    },
    emits: [
        'load-pin',
        'add-pin',
    ],
    methods: {
        reset() {
            this.tab = 'info';
        },
        refresh() {
            // Preserve selection by reselecting the active item in the current tab
            this.reselectActive();
        },
        reselectActive() {
            try {
                if (this.tab === 'entries') {
                    const id = this.$refs.entries?.entry?.id;
                    if (id && this.$refs.entries?.select) {
                        this.$nextTick(() => this.$refs.entries.select(id));
                    }
                } else if (this.tab === 'states') {
                    const q = this.$refs.states?.state?.question;
                    if (q && this.$refs.states?.select) {
                        this.$nextTick(() => this.$refs.states.select(q));
                    }
                }
            } catch(e) {
                console.error('WorldStateManagerWorld: reselectActive failed', e);
            }
        },
        navigate(selection) {
            if(selection === '$NEW_ENTRY') {
                console.log('navigating to new entry');
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
                const colonIndex = selection.indexOf(':');
                if (colonIndex === -1) {
                    this.tab = 'info';
                    return;
                }
                const type = selection.substring(0, colonIndex);
                const id = selection.substring(colonIndex + 1);

                if(type === 'entry') {
                    this.tab = 'entries';
                    this.$nextTick(() => {
                        this.$refs.entries.select(id);
                    });
                } else if(type === 'state') {
                    this.tab = 'states';
                    this.$nextTick(() => {
                        this.$refs.states.select(id);
                    });
                } else {
                    this.tab = 'info';
                }

            }
        }
    }
}

</script>