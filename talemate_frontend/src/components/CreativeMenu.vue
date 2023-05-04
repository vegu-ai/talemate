<template>
    <div v-if="scene.environment === 'creative'">
        <v-list-subheader class="text-uppercase">
            <v-icon class="mr-1">mdi-account</v-icon>Characters
        </v-list-subheader>

        <div ref="charactersContainer">
            <v-list>
                <v-list-item density="compact" v-for="(character,index) in scene.characters" :key="index">
                    <v-list-item-title>
                        {{ character.name }}
                    </v-list-item-title>
                    <div class="text-center mt-1 mb-1">

                        <v-tooltip text="Remove">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" color="red" icon="mdi-account-cancel" @click.stop="removeCharacterFromScene(character.name)"></v-btn>

                            </template>
                        </v-tooltip>
                        <v-tooltip text="Edit character">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" icon="mdi-account-edit" @click.stop="openCharacterCreatorForCharacter(character.name)"></v-btn>

                            </template>
                        </v-tooltip>

                        <v-tooltip v-if="false" text="Character sheet">
                            <template v-slot:activator="{ props }">
                                <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" icon="mdi-account-details"></v-btn>

                            </template>
                        </v-tooltip>
                    </div>
                    <v-divider></v-divider>
                </v-list-item>
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
    methods: {
        toggle() {
            this.expanded = !this.expanded;
        },

        removeCharacterFromScene(character) {

            let confirm = window.confirm(`Are you sure you want to remove ${character} from the scene?`);

            if(!confirm) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: `!remove_character:${character}`,
            }));
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