<template>
    <v-list-subheader class="text-uppercase">
        <v-icon class="mr-1">mdi-earth</v-icon>World
        <v-progress-circular class="ml-1 mr-3" size="14" v-if="requesting" indeterminate color="primary"></v-progress-circular>   
        <v-tooltip v-else  text="Update Worldstate">
            <template v-slot:activator="{ props }">
                <v-btn :disabled="isInputDisabled()"  size="x-small" icon="mdi-refresh" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="refresh()"></v-btn>
            </template>
        </v-tooltip>

        <v-tooltip text="Worldstate Manager">
            <template v-slot:activator="{ props }">
                <v-btn size="x-small" icon="mdi-book-open-page-variant" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="openWorldStateManager"></v-btn>
            </template>
        </v-tooltip>

    </v-list-subheader>


    <div ref="charactersContainer">   

        <!-- CHARACTERS -->

        <v-expansion-panels density="compact" v-for="(character,name) in characters" :key="name">
            <v-expansion-panel rounded="0" density="compact">

                <!-- TITLE: CHARACTER NAME -->

                <v-expansion-panel-title class="text-subtitle-2" diable-icon-rotate>
                    {{ name }}
                    <v-chip v-if="character.emotion !== null && character.emotion !== ''" label size="x-small" variant="outlined" class="ml-1">{{ character.emotion }}</v-chip>
                    <template v-slot:actions>
                        <v-icon icon="mdi-account"></v-icon>
                    </template>
                </v-expansion-panel-title>

                <!-- SNAPSHOT: CHARACTER -->
                        
                <v-expansion-panel-text class="text-body-2">
                    {{ character.snapshot }}

                    <!-- ACTIONS: LOOK AT, CHARACTER SHEET, PERSIST -->

                    <div class="text-center mt-1">
                        <v-tooltip text="Look at">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="lookAtCharacter(name)" icon="mdi-eye"></v-btn>

                            </template>
                        </v-tooltip>

                        <v-tooltip v-if="characterSheet().characterExists(name)" text="Character details">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="openCharacterSheet(name)" icon="mdi-account-details"></v-btn>

                            </template>
                        </v-tooltip>
                        <v-tooltip v-else text="Make this character real, adding it to the scene as an actor.">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="persistCharacter(name)" icon="mdi-chat-plus-outline"></v-btn>

                            </template>
                        </v-tooltip>
                    </div>
                    <v-divider class="mt-1"></v-divider>

                    <!-- TRACKED STATES -->

                    <div>
                        <v-tooltip v-for="(state,index) in trackedCharacterStates(name)"
                        :key="index"
                        max-width="500px"
                        class="pre-wrap"
                        :text="state.answer">
                            <template v-slot:activator="{ props }">
                                <v-chip 
                                label 
                                v-bind="props"
                                size="x-small"
                                variant="outlined"
                                color="grey-lighten-1"
                                prepend-icon="mdi-image-auto-adjust"
                                @click="openWorldStateManager('characters', name, 'reinforce', state.question)"
                                class="mt-1">
                                    {{ state.question }}
                                </v-chip>
                            </template>
                        </v-tooltip>

                    </div>

                </v-expansion-panel-text>
            </v-expansion-panel>
        </v-expansion-panels>

    </div>
    <div ref="objectsContainer">   

        <v-expansion-panels density="compact" v-for="(obj,name) in items" :key="name">
            <v-expansion-panel rounded="0" density="compact">
                <v-expansion-panel-title class="text-subtitle-2" diable-icon-rotate>
                    {{ name}}
                    <template v-slot:actions>
                        <v-icon icon="mdi-cube"></v-icon>
                    </template>
                </v-expansion-panel-title>
                        
                <v-expansion-panel-text class="text-body-2">
                    {{ obj.snapshot }}
                    <div class="text-center mt-1">
                        <v-tooltip text="Look at">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="lookAtItem(name)" icon="mdi-eye"></v-btn>

                            </template>
                        </v-tooltip>
                    </div>
                    <v-divider class="mt-1"></v-divider>
                </v-expansion-panel-text>
            </v-expansion-panel>
        </v-expansion-panels>

    </div>

    <div ref="extrasContainer">

        <v-expansion-panels density="compact">
            <!-- active pin container-->
            <v-expansion-panel rounded="0" density="compact"  v-if="activePins.length > 0">
                <v-expansion-panel-title class="text-subtitle-2" diable-icon-rotate>
                    Active Pins ({{ activePins.length }})
                    <template v-slot:actions>
                        <v-icon icon="mdi-pin"></v-icon>
                    </template>
                </v-expansion-panel-title>
                <v-expansion-panel-text>
                    <div class="mt-1 text-caption" v-for="(pin,index) in activePins" :key="index">
                        {{ truncatedPinText(pin) }}
                        <v-btn rounded="sm" variant="text" size="x-small" class="ml-1"  @click.stop="openWorldStateManager('pins')" icon="mdi-book-open-page-variant"></v-btn>
                        <v-divider></v-divider>
                    </div>
                    <!--

                    <v-list density="compact">
                        <v-list-item v-for="(pin,index) in activePins" :key="index">
                            <v-list-item-subtitle>{{ pin.text }}</v-list-item-subtitle>
                        </v-list-item>
                    </v-list>
                    -->
                </v-expansion-panel-text>
            </v-expansion-panel>
        </v-expansion-panels>

    </div>
    <WorldStateManager ref="worldStateManager" />
</template>

<script>
import WorldStateManager from './WorldStateManager.vue';

export default {
    name: 'WorldState',
    data() {
        return {
            characters: {},
            items: {},
            location: null,
            requesting: false,
            sceneTime: null,
            reinforce: {},
            activePins: [],
        }
    },
    components: {
        WorldStateManager,
    },

    inject: [
        'getWebsocket', 
        'registerMessageHandler', 
        'setWaitingForInput',
        'openCharacterSheet',
        'characterSheet',
        'isInputDisabled',
    ],

    methods: {
        truncatedPinText(pin) {
            let max = 75;
            if(pin.text.length > max) {
                return pin.text.substring(0,max) + "...";
            } else {
                return pin.text;
            }
        },
        truncatedStateText(state) {
            let max = 512;
            if(state.answer.length > max) {
                return state.answer.substring(0,max) + "...";
            } else {
                return state.answer;
            }
        },
        openWorldStateManager(tab, sub1, sub2, sub3) {
            this.$refs.worldStateManager.show(tab, sub1, sub2, sub3);
        },
        lookAtCharacter(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: `!narrate_c:${name}`,
            }));
        },
        persistCharacter(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: `!pc:${name}`,
            }));
        },
        lookAtItem(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: `!narrate_q:describe the apperance of ${name}.:true`,
            }));
        },
        refresh() {
            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: '!ws',
            }));
        },
        trackedCharacterState(name, question) {
            // cycle through reinforce and return true if the character has a tracked state for this question
            // by checking the `character` and `question` properties of the reinforce object

            // replace {character_name} with {name} in question
            question = question.replace("{character_name}", name);

            for(let state of this.reinforce) {
                if(state.character === name && state.question === question) {
                    return state;
                }
            }
            return null;
        },
        trackedCharacterStates(name) {
            // cycle through reinforce and return the states that are tracked for this character
            // by checking the `character` property of the reinforce object
            let states = [];

            for(let state of this.reinforce) {
                if(state.character === name) {
                    states.push(state);
                }
            }
            
            return states;
        },
        handleMessage(data) {
            if(data.type === 'world_state') {
                this.characters = data.data.characters;
                this.items = data.data.items;
                this.location = data.data.location;
                this.requesting = (data.status==="requested")
                this.reinforce = data.data.reinforce;
            } else if (data.type == "scene_status") {
                this.sceneTime = data.data.scene_time;
                this.activePins = data.data.active_pins;
                console.log("PINS", data.data.active_pins);
            }
        },
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped>
.pre-wrap {
    white-space: pre-wrap;
}
</style>