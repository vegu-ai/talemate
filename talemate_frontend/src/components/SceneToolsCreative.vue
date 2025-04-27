<template>
    <v-menu>
        <template v-slot:activator="{ props }">
            <v-btn class="hotkey mx-1" v-bind="props" :disabled="disabled" color="primary" icon>
                <v-icon>mdi-puzzle-edit</v-icon>
                <v-icon v-if="potentialNewCharactersExist()" class="btn-notification" color="warning">mdi-human-greeting</v-icon>
            </v-btn>
        </template>
        <v-list>
            <v-list-subheader>Creative Tools</v-list-subheader>
            
            <!-- deactivate active characters -->
            <v-list-item v-for="(character, index) in deactivatableCharacters" :key="index"
                @click="deactivateCharacter($event, character)">
                <template v-slot:prepend>
                    <v-icon color="secondary">mdi-exit-run</v-icon>
                </template>
                <v-list-item-title>Take out of scene: {{ character }}<v-chip variant="text" color="info" class="ml-1" size="x-small">Ctrl: no narration</v-chip></v-list-item-title>
                <v-list-item-subtitle>Make {{ character }} a passive character.</v-list-item-subtitle>
            </v-list-item>

            <!-- reactivate inactive characters -->
            <v-list-item v-for="(character, index) in inactiveCharacters" :key="index"
                @click="activateCharacter($event, character)">
                <template v-slot:prepend>
                    <v-icon color="secondary">mdi-human-greeting</v-icon>
                </template>
                <v-list-item-title>Call into scene: {{ character }}<v-chip variant="text" color="info" class="ml-1" size="x-small">Ctrl: no narration</v-chip></v-list-item-title>
                <v-list-item-subtitle>Make {{ character }} an active character.</v-list-item-subtitle>
            </v-list-item>

            <!-- persist passive characters -->
            <v-list-item v-for="(character, index) in potentialNewCharacters" :key="index"
                @click="introduceCharacter($event, character)">
                <template v-slot:prepend>
                    <v-icon color="warning">mdi-human-greeting</v-icon>
                </template>
                <v-list-item-title>Introduce {{ character }}<v-chip variant="text" color="info" class="ml-1" size="x-small">Ctrl: no narration</v-chip></v-list-item-title>
                <v-list-item-subtitle>Make {{ character }} an active character.</v-list-item-subtitle>
            </v-list-item>

            <!-- static tools -->
            <v-list-item v-for="(option, index) in creativeGameMenuFiltered" :key="index"
                @click="sendHotButtonMessage('!' + option.value)"
                :prepend-icon="option.icon">
                <v-list-item-title>{{ option.title }}</v-list-item-title>
                <v-list-item-subtitle>{{ option.description }}</v-list-item-subtitle>
            </v-list-item>
        </v-list>
    </v-menu>
</template>

<script>
export default {
    name: 'SceneToolsCreative',
    props: {
        activeCharacters: Array,
        inactiveCharacters: Array,
        passiveCharacters: Array,
        playerCharacterName: String,
        scene: Object,
        disabled: Boolean,
    },
    inject: ['getWebsocket'],
    computed: {
        deactivatableCharacters() {
            // activeCharacters without playerCharacterName
            let characters = [];
            for (let character of this.activeCharacters) {
                if (character !== this.playerCharacterName) {
                    characters.push(character);
                }
            }
            return characters;
        },
        potentialNewCharacters() {
            // return all entries in passiveCharacters that dont exist in
            // inactiveCharacters
            let newCharacters = [];
            for (let character of this.passiveCharacters) {
                if (!this.inactiveCharacters.includes(character)) {
                    newCharacters.push(character);
                }
            }
            return newCharacters;
        },
        creativeGameMenuFiltered() {
            return this.creativeGameMenu.filter(option => {
                if (option.condition) {
                    return option.condition();
                } else {
                    return true;
                }
            });
        }
    },
    data() {
        return {
            creativeGameMenu: [
                {
                    "value": "pc:prompt", 
                    "title": "Introduce new character (Directed)", 
                    "icon": "mdi-account-plus", 
                    "description": "Generate a new active character, based on prompt."
                },
                {
                    "value": "setenv_creative", 
                    "title": "Creative Mode", 
                    "icon": "mdi-puzzle-edit",
                    "description": "Switch to creative mode (very early experimental version)",
                    "condition": () => { return this.isEnvironment('scene') }
                },
                {
                    "value": "setenv_scene", 
                    "title": "Exit Creative Mode", 
                    "icon": "mdi-gamepad-square",
                    "description": "Switch to game mode",
                    "condition": () => { return this.isEnvironment('creative') }
                }
            ],
        }
    },
    methods: {
        potentialNewCharactersExist() {
            return this.potentialNewCharacters.length > 0;
        },
        
        isEnvironment(typ) {
            if(!this.scene) {
                return false;
            }
            return this.scene.environment == typ;
        },
        
        sendHotButtonMessage(message) {
            this.getWebsocket().send(JSON.stringify({ type: 'interact', text: message }));
        },
        
        activateCharacter(ev, name) {
            let modifyNoNarration = ev.ctrlKey;
            if(!modifyNoNarration) {
                this.sendHotButtonMessage('!char_a:' + name);
            } else {
                this.sendHotButtonMessage('!char_a:' + name + ':no');
            }
        },

        deactivateCharacter(ev, name) {
            let modifyNoNarration = ev.ctrlKey;
            if(!modifyNoNarration) {
                this.sendHotButtonMessage('!char_d:' + name);
            } else {
                this.sendHotButtonMessage('!char_d:' + name + ':no');
            }
        },

        introduceCharacter(ev, name) {
            let modifyNoNarration = ev.ctrlKey;
            if(!modifyNoNarration) {
                this.sendHotButtonMessage('!persist_character:' + name);
            } else {
                this.sendHotButtonMessage('!persist_character:' + name + ':no');
            }
        }
    }
}
</script>
<style scoped>
.btn-notification {
    position: absolute;
    top: 0px;
    right: 0px;
    font-size: 15px;
    border-radius: 50%;
    width: 20px;
    height: 20px;
    display: flex;
    justify-content: center;
    align-items: center;
}
</style>