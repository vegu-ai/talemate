<template>

    <!-- character list -->
    <v-tabs direction="vertical" v-model="selected" color="secondary" class="mt-2">
        <v-tab prepend-icon="mdi-account" v-for="character in characterList.characters" :key="character.name" :value="character.name">
            <div class="text-left text-caption">
                {{ character.name }}
                <div class="text-caption">
                <v-chip v-if="character.is_player === true" label size="x-small"
                    variant="tonal" color="info">Player</v-chip>
                <v-chip v-else-if="character.is_player === false" label size="x-small"
                    variant="tonal" color="warning">AI</v-chip>
                <v-chip v-if="character.active === true && character.is_player === false"
                    label size="x-small" variant="tonal" color="success"
                    class="ml-1">Active</v-chip>
                </div>

            </div>
        </v-tab>
    </v-tabs>

</template>

<script>
export default {
    name: "WorldStateManagerMenuCharacterTools",
    components: {
    },
    props: {
        scene: Object,
        character: Object,
        title: String,
        icon: String,
    },
    watch:{
        selected: {
            immediate: true,
            handler(selected) {
                console.log("selection",selected)
                this.$emit('world-state-manager-navigate', 'characters', selected, 'description');
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
            characterList: {
                characters: [],
            },
            selected: null,
        }
    },
    emits: [
        'world-state-manager-navigate'
    ],
    methods: {
        requestCharacterList() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_list',
            }));
        },

        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            } else if (message.action === 'character_list') {
                this.characterList = message.data;
            } else if(message.action === 'character_deleted') {
                if(this.selected === message.data.name) {
                    this.selected = null;
                }
            } 
        }
    },
    mounted() {
        this.requestCharacterList();
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    }
}

</script>