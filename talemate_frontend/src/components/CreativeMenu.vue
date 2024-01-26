<template>
    <div v-if="scene.environment === 'creative'">
        <v-list-subheader class="text-uppercase">
            <v-icon class="mr-1">mdi-account</v-icon>Characters
        </v-list-subheader>

        <div ref="charactersContainer">
            <v-list density="compact">
                <!-- active characters -->
                <v-list-item density="compact" v-for="(character,index) in scene.characters" :key="index">
                    <v-list-item-title>
                        {{ character.name }}
                    </v-list-item-title>
                    <div class="text-center mt-1 mb-1">

                        <v-tooltip text="Permanently Delete">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" color="red" icon="mdi-account-cancel" @click.stop="removeCharacterFromScene(character.name)"></v-btn>

                            </template>
                        </v-tooltip>

                        <v-tooltip text="Deactivate">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" color="secondary" icon="mdi-exit-run" @click.stop="getWebsocket().send(JSON.stringify({type: 'interact', text: '!char_d:'+character.name+':no'}))"></v-btn>

                            </template>
                        </v-tooltip>

                        <v-tooltip text="Edit character">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" icon="mdi-account-edit" @click.stop="openWorldStateManager('characters',character.name, 'description')"></v-btn>
                            </template>
                        </v-tooltip>

                        <v-tooltip text="Open character template in character creator" v-if="character.base_attributes._template">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" icon="mdi-badge-account-outline" @click.stop="openCharacterCreatorForCharacter(character.name)"></v-btn>
                            </template>
                        </v-tooltip>

                    </div>
                    <v-divider></v-divider>
                </v-list-item>
                
                <!-- inactive characters -->

                <v-list-item v-for="(character_name, index) in scene.inactive_characters" density="compact" :key="index">
                    <v-list-item-title class="text-grey-darken-1">
                        {{ character_name }}
                    </v-list-item-title>
                    <div class="text-center mt-1 mb-1">

                        <v-tooltip text="Permanently Delete">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" color="red" icon="mdi-account-cancel" @click.stop="removeCharacterFromScene(character_name)"></v-btn>

                            </template>
                        </v-tooltip>

                        <v-tooltip text="Activate (call to scene)">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" color="secondary" icon="mdi-human-greeting" @click.stop="getWebsocket().send(JSON.stringify({type: 'interact', text: '!char_a:'+character_name+':no'}))"></v-btn>

                            </template>
                        </v-tooltip>
                        <v-tooltip text="Edit character">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" icon="mdi-account-edit" @click.stop="openWorldStateManager('characters',character_name, 'description')"></v-btn>
                            </template>
                        </v-tooltip>
                    </div>
                    <v-divider></v-divider>
                </v-list-item>


                <!-- add / import character -->

                <v-list-item>
                    <v-tooltip text="Add character">
                        <template v-slot:activator="{ props }">
                            <v-btn @click="openCharacterCreator" v-bind="props" density="comfortable" class="mt-1 mr-1" size="small" color="primary" icon="mdi-account-plus" rounded="sm"></v-btn>
                        </template>
                    </v-tooltip>
                    <v-tooltip text="Import character from other scene">
                        <template v-slot:activator="{ props }">
                            <v-btn @click="openCharacterImporter" v-bind="props" density="comfortable" class="mt-1" size="small" color="primary" icon="mdi-account-arrow-right" rounded="sm"></v-btn>
                        </template>
                    </v-tooltip>
                </v-list-item>
            </v-list>
        </div>
    
        
        <v-list-subheader class="text-uppercase">
            <v-icon class="mr-1">mdi-image</v-icon>Scenario
        </v-list-subheader>

        <v-list ref="sceneContainer">
            <v-list-item>
                <v-list-item-title>
                    {{ scene.name }}
                </v-list-item-title>
                <v-btn block color="primary" @click="openSceneCreator" prepend-icon="mdi-pencil">Edit Scenario</v-btn>
            </v-list-item>    
        </v-list>

    
    </div>

</template>

<script>
export default {
    name: 'CreativeMenu',
    data() {
        return {
            expanded: false,
            scene: {
                characters: {},
                environment: null,
                description: null,
                name: null,
                intro: null,
            }
        }
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'isConnected', 
        'openCharacterCreator',
        'openCharacterCreatorForCharacter',
        'openCharacterImporter',
        'openSceneCreator',
    ],
    emits: [
        'open-world-state-manager',
    ],
    methods: {
        toggle() {
            this.expanded = !this.expanded;
        },

        removeCharacterFromScene(character) {

            let confirm = window.confirm(`Are you sure you want to remove ${character} from the game?`);

            if(!confirm) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: `!remove_character:${character}`,
            }));
        },

        openWorldStateManager(tab, sub1, sub2, sub3) {
            this.$emit('open-world-state-manager', tab, sub1, sub2, sub3);
        },

        handleMessage(data) {
            if(data.type === 'scene_status' && data.status === 'started') {
                this.scene = data.data;
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>


<style scoped></style>