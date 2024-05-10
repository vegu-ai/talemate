<template>
    <CoverImage ref="coverImageCharacter" :target="character" :type="'character'" :allow-update="true" />

    <v-list v-if="character !== null && !character.is_player">
        
        <!-- DEACTIVATE CHARACTER -->

        <v-list-item v-if="character.active">
            <v-tooltip max-width="300" :text="`Immediately deactivate ${character.name}. This will remove them from the scene, but they will still be available in the character list, and can be recalled at any point.`">
                <template v-slot:activator="{ props }">
                    <v-btn @click.stop="deactivateCharacter" v-bind="props" variant="tonal" block color="secondary" prepend-icon="mdi-exit-run">Deactivate {{ character.name }}</v-btn>

                </template>
            </v-tooltip>
        </v-list-item>

        <v-list-item v-else>
            <v-tooltip max-width="300" :text="`Immediately activate ${character.name}. This will re-add them to the scene and allow to participate in it.`">
                <template v-slot:activator="{ props }">
                    <v-btn @click.stop="activateCharacter" v-bind="props" variant="tonal" block color="primary" prepend-icon="mdi-human-greeting">Activate {{ character.name }}</v-btn>
                </template>
            </v-tooltip>
        </v-list-item>

        <v-divider></v-divider>

        <!-- DELETE CHARACTER -->

        <v-list-item>
            <v-tooltip  v-if="confirmDelete === null"  max-width="300" :text="`Permanently delete ${character.name} - will ask for confirmation and cannot be undone.`">
                <template v-slot:activator="{ props }">
                    <v-btn @click.stop="confirmDelete=''" variant="tonal" v-bind="props" block color="red-darken-2" prepend-icon="mdi-close-box-outline">Delete {{ character.name }}</v-btn>
                </template>
            </v-tooltip>

            <div v-else class="mt-2">
                <v-list-item-subtitle>Confirm Deletion</v-list-item-subtitle>
                <p class="text-grey text-caption">
                    Confirm that you want to delete <span class="text-primary">{{ character.name }}</span>, by
                    typing the character name and clicking <span class="text-red-darken-2">Delete</span> once more.
                    This cannot be undone.
                </p>
                <v-text-field :disabled="deleteBusy" v-model="confirmDelete" color="red-darken-2" hide-details @keydown.enter="deleteCharacter" />
                <v-btn v-if="confirmDelete !== character.name" :disabled="deleteBusy" variant="tonal" block color="secondary" prepend-icon="mdi-cancel" @click.stop="confirmDelete = null">Cancel</v-btn>
                <v-btn v-else :disabled="deleteBusy" variant="tonal" block color="red-darken-2" prepend-icon="mdi-close-box-outline" @click.stop="deleteCharacter">Delete {{ character.name }}</v-btn>
            </div>
        </v-list-item>
    </v-list>
</template>

<script>
import CoverImage from './CoverImage.vue';

export default {
    name: "WorldStateManagerMenuCharacterTools",
    components: {
        CoverImage,
    },
    props: {
        scene: Object,
        character: Object,
    },
    watch:{
        character: {
            immediate: true,
            handler(character, characterOld) {
                if(characterOld && (!character || character.name != characterOld.name)) {
                    this.confirmDelete = null;
                    this.deleteBusy = false;
                }
            }
        }
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
    ],
    data() {
        return {
            confirmDelete: null,
            deleteBusy: false,
        }
    },
    methods: {
        deleteCharacter() {
            if (this.confirmDelete === this.character.name) {
                this.deleteBusy = true;
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager',
                    action: 'delete_character',
                    name: this.character.name,
                }));
            }
        },
        deactivateCharacter() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'deactivate_character',
                name: this.character.name,
            }));
        },
        activateCharacter() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'activate_character',
                name: this.character.name,
            }));
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            } else if(message.action === 'character_deleted') {
                this.deleteBusy = false;
                this.confirmDelete = null;
            }
        }
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    }
}

</script>