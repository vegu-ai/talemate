<template>
    <v-list-subheader class="text-uppercase">
        <v-icon class="mr-1">mdi-earth</v-icon>World
        <v-progress-circular class="ml-1 mr-3" size="14" v-if="requesting" indeterminate color="primary"></v-progress-circular>   
        <v-btn v-else size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="refresh()" icon="mdi-refresh"></v-btn>
     
    </v-list-subheader>

    <div ref="charactersContainer">   

        <v-expansion-panels density="compact" v-for="(character,name) in characters" :key="name">
            <v-expansion-panel rounded="0" density="compact">
                <v-expansion-panel-title class="text-subtitle-2" diable-icon-rotate>
                    {{ name }}
                    <v-chip label size="x-small" variant="outlined" class="ml-1">{{ character.emotion }}</v-chip>
                    <template v-slot:actions>
                        <v-icon icon="mdi-account"></v-icon>
                    </template>
                </v-expansion-panel-title>
                        
                <v-expansion-panel-text class="text-body-2">
                    {{ character.snapshot }}
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
</template>

<script>
export default {
    name: 'WorldState',
    data() {
        return {
            characters: {},
            items: {},
            location: null,
            requesting: false,
        }
    },

    inject: [
        'getWebsocket', 
        'registerMessageHandler', 
        'setWaitingForInput',
        'openCharacterSheet',
        'characterSheet',
    ],

    methods: {
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
        handleMessage(data) {
            if(data.type === 'world_state') {
                this.characters = data.data.characters;
                this.items = data.data.items;
                this.location = data.data.location;
                this.requesting = (data.status==="requested")
            }
        },
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped>

</style>