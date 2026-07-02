<template>
<v-list density="compact">
    <v-list-subheader class="text-uppercase">
        <v-icon class="mr-1">mdi-earth</v-icon>World
        <template v-if="requesting">
            <v-progress-circular class="ml-1" size="14" indeterminate="disable-shrink" color="primary"></v-progress-circular>
            <v-tooltip text="Cancel world state update">
                <template v-slot:activator="{ props }">
                    <v-btn size="x-small" icon="mdi-close" class="ml-1 mr-1" v-bind="props" variant="text" density="comfortable" rounded="sm" @click.stop="cancelRequest()"></v-btn>
                </template>
            </v-tooltip>
        </template>
        <v-tooltip v-else :text="refreshTooltip">
            <template v-slot:activator="{ props }">
                <v-btn :disabled="busy"  size="x-small" icon="mdi-refresh" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="refresh($event)"></v-btn>
            </template>
        </v-tooltip>
    </v-list-subheader>

    <v-sheet ref="worldStateContainer">

        <!-- empty (no characters or objects) -->

        <v-card elevation="7" v-if="Object.keys(characters).length === 0 && Object.keys(items).length === 0" class="text-center text-caption mx-3" density="compact" variant="tonal" color="grey">
            World state has not been updated yet.
        </v-card>

        <div ref="charactersContainer">   

            <!-- CHARACTERS -->

            <v-expansion-panels density="compact" v-for="(character,name) in characters" :key="name">
                <v-expansion-panel rounded="0" density="compact">

                    <!-- TITLE: CHARACTER NAME -->

                    <v-expansion-panel-title class="text-subtitle-2" diable-icon-rotate>
                        {{ name }}
                        <!-- <v-chip v-if="character.emotion !== null && character.emotion !== ''" label size="x-small" variant="outlined" class="ml-1">{{ character.emotion }}</v-chip> -->
                        <span class="text-caption ml-1 text-muted">{{ character.emotion }}</span>
                        <template v-slot:actions>
                            <v-icon v-if="characterSuggestions(name)" color="highlight5" class="mr-1">mdi-lightbulb-on</v-icon>
                            <div v-else-if="getCharacterAvatar(name)" class="character-avatar-square mr-1">
                                <v-img :src="getCharacterAvatarSrc(name)" cover />
                            </div>
                            <v-icon v-else icon="mdi-account"></v-icon>
                        </template>
                    </v-expansion-panel-title>

                    <!-- SNAPSHOT: CHARACTER -->
                            
                    <v-expansion-panel-text class="text-body-2">
                        {{ character.snapshot }}

                        <!-- ACTIONS: LOOK AT, PERSIST, MANAGE -->

                        <div class="text-center mt-1">
                            <v-tooltip :text="'Look at '+name">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="lookAtCharacter(name)" icon="mdi-eye"></v-btn>

                                </template>
                            </v-tooltip>
                            <v-tooltip v-if="character.snapshot && !characterIsKnown(name)" :text="'Add detail to '+name">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="examineCharacter(name, character.snapshot)" icon="mdi-plus"></v-btn>

                                </template>
                            </v-tooltip>
                            <v-tooltip v-if="!characterExists(name)" text="Make this character real, adding it to the scene as an actor.">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="persistCharacter(name)" icon="mdi-human-greeting"></v-btn>

                                </template>
                            </v-tooltip>
                            <v-tooltip v-if="characterExists(name)" text="Manage character">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="openWorldStateManager('characters', name, 'description')" icon="mdi-book-open-page-variant"></v-btn>

                                </template>
                            </v-tooltip>
                            <v-tooltip v-if="characterSuggestions(name)" text="Review proposed changes for this character">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" color="highlight5" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="openWorldStateManager('suggestions', 'character-'+name)" icon="mdi-lightbulb-on"></v-btn>

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
                            <v-tooltip v-if="obj.snapshot" :text="'Add detail to '+name">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="examineItem(name, obj.snapshot)" icon="mdi-plus"></v-btn>

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
                            <v-btn rounded="sm" variant="text" size="x-small" class="ml-1"  @click.stop="openWorldStateManager('pins', pin.pin.entry_id)" icon="mdi-book-open-page-variant"></v-btn>
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
                
                <!-- tracked states -->
                <v-expansion-panel rounded="0" density="compact" v-if="hasAnyWorldState">
                    <v-expansion-panel-title class="text-subtitle-2" diable-icon-rotate>
                        World
                        <template v-slot:actions>
                            <v-icon icon="mdi-earth"></v-icon>
                        </template>
                    </v-expansion-panel-title>
                    <v-expansion-panel-text>

                        <!-- TRACKED STATES -->

                        <div>

                            <v-tooltip v-for="(state,index) in trackedWorldStates()"
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
                                    @click="openWorldStateManager('world', 'states', state.question)"
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
    </v-sheet>
</v-list>
</template>

<script>

import VisualAssetsMixin from './VisualAssetsMixin.js';
import {
    dispatchExamineEntity,
    dispatchLookAtEntity,
    isKnownSceneCharacter,
} from '@/utils/entityActions';
import { isPrimaryModifier, primaryModifierLabel } from '@/utils/keyboardModifiers';

export default {
    name: 'WorldState',
    mixins: [VisualAssetsMixin],
    data() {
        return {
            characters: {},
            suggestions: [],
            items: {},
            location: null,
            requesting: false,
            sceneTime: null,
            reinforce: {},
            activePins: [],
            worldStateMaxHeight: null,
            hasAnyWorldState: false,
        }
    },

    props: {
        busy: Boolean,
    },

    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'setWaitingForInput',
        'isInputDisabled',
        'formatWorldStateTemplateString',
        'scene',
        'requestSceneAssets',
    ],

    emits: [
        'passive-characters',
        'open-world-state-manager'
    ],

    computed: {
        sceneData() {
            return this.scene ? this.scene() : null;
        },
        assetsMap() {
            return (this.sceneData?.data?.assets?.assets) || {};
        },
        refreshTooltip() {
            return `Update world snapshot (${primaryModifierLabel}+click to wipe and start fresh)`;
        },
    },

    methods: {
        onResize() {
            this.worldStateMaxHeight = this.availableHeight();
        },
        availableHeight() {
            // screen height - $refs.worldStateContainer top offset
            if(this.$refs.charactersContainer == null) return "500px";
            let maxHeight = (window.innerHeight - this.$refs.charactersContainer.getBoundingClientRect().top - 50)+"px";
            return maxHeight;
        },
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
            this.$emit('open-world-state-manager', tab, sub1, sub2, sub3);
        },
        passiveCharacters() {
            let characters = [];
            for(let character in this.characters) {
                if(!this.characterExists(character)) {
                    characters.push(character);
                }
            }
            this.$emit('passive-characters', characters);
        },
        lookAtCharacter(name) {
            dispatchLookAtEntity(this.getWebsocket(), {
                name,
                kind: 'character',
                isKnownCharacter: this.characterIsKnown(name),
            });
        },
        persistCharacter(name) {
            this.getWebsocket().send(JSON.stringify(
                {
                    type: 'director',
                    action: 'persist_character',
                    name: name,
                }
            ));
        },
        lookAtItem(name) {
            // kind !== 'character' falls through to the describe query
            // regardless of isKnownCharacter.
            dispatchLookAtEntity(this.getWebsocket(), {
                name,
                kind: 'item',
                isKnownCharacter: false,
            });
        },
        examineCharacter(name, snapshot) {
            dispatchExamineEntity(this.getWebsocket(), {
                name,
                kind: 'character',
                snapshot,
            });
        },
        examineItem(name, snapshot) {
            dispatchExamineEntity(this.getWebsocket(), {
                name,
                kind: 'item',
                snapshot,
            });
        },
        refresh(event) {
            const reset = !!event && isPrimaryModifier(event);
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_agent',
                action: 'request_update',
                reset,
            }));
        },
        cancelRequest() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_agent',
                action: 'cancel_request_update',
            }));
        },
        trackedCharacterState(name, question) {
            // cycle through reinforce and return true if the character has a tracked state for this question
            // by checking the `character` and `question` properties of the reinforce object

            // replace {character_name} with {name} in question
            question = this.formatWorldStateTemplateString(question, name);

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
        trackedWorldState(question) {
            // cycle through reinforce and return true if the world has a tracked state for this question
            // by checking the `character` property of the reinforce object
            question = this.formatWorldStateTemplateString(question, "the characters");
            for(let state of this.reinforce) {
                if(state.character === null && state.question === question) {
                    return state;
                }
            }
            return null;
        },

        trackedWorldStates() {
            // cycle through reinforce and return the states that are tracked for the world
            // by checking the `character` property of the reinforce object
            let states = [];

            for(let state of this.reinforce) {
                if(state.character === null) {
                    states.push(state);
                }
            }
            
            return states;
        },

        characterSuggestions(name) {
            for(let suggestion of this.suggestions) {
                if(suggestion.name === name && suggestion.type === 'character') {
                    return true;
                }
            }
            return false;
        },
        characterExists(name) {
            if (!this.sceneData || !this.sceneData.data || !this.sceneData.data.characters) {
                return false;
            }
            for (let character of this.sceneData.data.characters) {
                if (name.toLowerCase().indexOf(character.name.toLowerCase()) !== -1 || character.name.toLowerCase().indexOf(name.toLowerCase()) !== -1) {
                    return true;
                }
            }
            return false;
        },
        // Exact-match roster check (active + inactive) for the Add Detail gate.
        // Distinct from characterExists (fuzzy/active-only), which the
        // persist/manage buttons rely on; the Add Detail gate needs the precise
        // "is this the same character that already has a sheet" answer.
        characterIsKnown(name) {
            return isKnownSceneCharacter(this.sceneData?.data, name);
        },
        getCharacterData(name) {
            if (!this.sceneData || !this.sceneData.data || !this.sceneData.data.characters) {
                return null;
            }
            // Find character in active characters
            const char = this.sceneData.data.characters.find(c => c.name === name);
            if (char) {
                return char;
            }
            // Also check inactive characters
            if (this.sceneData.data.inactive_characters) {
                return Object.values(this.sceneData.data.inactive_characters).find(c => c.name === name) || null;
            }
            return null;
        },
        getCharacterAvatar(name) {
            // Only show avatar if character exists in scene
            if (!this.characterExists(name)) {
                return null;
            }
            const characterData = this.getCharacterData(name);
            if (!characterData) {
                return null;
            }
            // Use current_avatar if available, otherwise fall back to avatar
            return characterData.current_avatar || characterData.avatar || null;
        },
        getCharacterAvatarSrc(name) {
            const avatarId = this.getCharacterAvatar(name);
            if (!avatarId) {
                return '';
            }
            const base64 = this.base64ById[avatarId];
            if (!base64) {
                return '';
            }
            const asset = this.assetsMap[avatarId];
            const mediaType = asset?.media_type || 'image/png';
            return `data:${mediaType};base64,${base64}`;
        },
        loadCharacterAvatars() {
            const avatarIds = [];
            for (const name in this.characters) {
                const avatarId = this.getCharacterAvatar(name);
                if (avatarId) {
                    avatarIds.push(avatarId);
                }
            }
            if (avatarIds.length > 0) {
                this.loadAssets(avatarIds);
            }
        },

        handleMessage(data) {
            // Handle scene_asset messages using mixin method
            this.handleSceneAssetMessage(data);
            
            if(data.type === 'world_state') {
                this.characters = data.data.characters;
                this.suggestions = data.data.suggestions;
                this.items = data.data.items;
                this.location = data.data.location;
                this.requesting = (data.status==="requested")
                console.log("WorldState.vue: world_state", data.data);
                this.reinforce = data.data.reinforce;

                // check if there is any entry in reinforce that doesnt have
                // character set, if there is, hasAnyWorldState is true

                this.hasAnyWorldState = false;
                for(let state of this.reinforce) {
                    if(state.character === null) {
                        this.hasAnyWorldState = true;
                        break;
                    }
                }

                this.passiveCharacters();
                
                // Load avatars for characters that exist in scene
                this.$nextTick(() => {
                    this.loadCharacterAvatars();
                });

                //this.onResize()
            } else if (data.type == "scene_status") {
                this.sceneTime = data.data.scene_time;
                this.activePins = data.data.active_pins;
                // Load avatars when scene status updates (characters may have changed)
                this.$nextTick(() => {
                    this.loadCharacterAvatars();
                });
                //this.onResize();
            } else if (data.type === 'scene_asset_character_avatar') {
                // Handle avatar changes
                if (data.asset_id) {
                    this.loadAssets([data.asset_id]);
                }
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
.character-avatar-square {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    overflow: hidden;
    flex-shrink: 0;
    display: inline-flex;
    transform: translateX(8px);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
    border: 2px solid rgb(var(--v-theme-avatar_border));
}
</style>