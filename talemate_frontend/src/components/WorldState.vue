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
        <v-tooltip v-else-if="!isPlaythroughActive()" :text="refreshTooltip">
            <template v-slot:activator="{ props }">
                <v-btn :disabled="busy"  size="x-small" icon="mdi-refresh" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="refresh($event)"></v-btn>
            </template>
        </v-tooltip>
    </v-list-subheader>

    <v-sheet ref="worldStateContainer">

        <!-- empty (no characters or objects) -->

        <v-card elevation="3" v-if="characterRoster.length === 0 && !showInactiveCharacters && Object.keys(items).length === 0" class="text-center text-body-small mx-3" density="compact" variant="tonal" color="muted">
            World state has not been updated yet.
        </v-card>

        <div ref="charactersContainer">   

            <!-- CHARACTERS -->

            <v-expansion-panels density="compact" v-for="row in characterRoster" :key="row.name">
                <v-expansion-panel rounded="0" density="compact" class="character-row" :class="{ 'character-row-active': row.active, 'character-row-background': !row.active }">

                    <!-- TITLE: CHARACTER NAME -->

                    <v-expansion-panel-title class="text-title-small" diable-icon-rotate>
                        {{ row.name }}
                        <v-tooltip v-if="row.manual" :text="manualEntryTooltip">
                            <template v-slot:activator="{ props }">
                                <v-icon v-bind="props" size="x-small" class="ml-1" color="muted">mdi-pin</v-icon>
                            </template>
                        </v-tooltip>
                        <span class="text-body-small ml-1 text-muted">{{ row.emotion }}</span>
                        <template v-slot:actions>
                            <span v-if="row.active" class="knowledge-marker-space"></span>
                            <v-icon v-if="characterSuggestions(row.name)" color="highlight5" class="mr-1">mdi-lightbulb-on</v-icon>
                            <div v-else-if="getCharacterAvatar(row.name)" class="character-avatar-square mr-1">
                                <v-img :src="getCharacterAvatarSrc(row.name)" cover />
                            </div>
                            <v-icon v-else icon="mdi-account"></v-icon>
                        </template>
                    </v-expansion-panel-title>

                    <Transition name="knowledge-marker">
                        <KnowledgeChangeMarker
                            v-if="row.active && !playthroughActive && knowledgeChanges.has(row.name)"
                            class="active-knowledge-marker"
                            :name="row.name"
                            :changes="knowledgeChanges.get(row.name)"
                            @pause="(reason, paused) => knowledgeNotifications.pause(row.name, reason, paused)"
                            @open="openWorldStateManager('characters', row.name, 'knowledge')"
                        />
                    </Transition>

                    <!-- SNAPSHOT: CHARACTER -->
                            
                    <v-expansion-panel-text class="text-body-medium">
                        <div class="mb-2">
                            <v-tooltip :text="characterKindTooltip(row)">
                                <template v-slot:activator="{ props }">
                                    <v-chip v-bind="props" class="character-kind" size="x-small" variant="tonal" :color="row.active ? 'primary' : 'secondary'" label tabindex="0">
                                        {{ row.active ? 'character' : 'background' }}
                                    </v-chip>
                                </template>
                            </v-tooltip>
                        </div>
                        {{ row.snapshot }}

                        <!-- ACTIONS: LOOK AT, PERSIST, MANAGE, TAKE OUT OF SCENE -->

                        <div class="text-center mt-1">
                            <v-tooltip v-if="!isPlaythroughActive()" :text="'Look at '+row.name">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="lookAtCharacter(row.name)" icon="mdi-eye"></v-btn>

                                </template>
                            </v-tooltip>
                            <v-tooltip v-if="row.snapshot && !characterIsKnown(row.name) && !isPlaythroughActive()" :text="'Add detail to '+row.name">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="examineCharacter(row.name, row.snapshot)" icon="mdi-plus"></v-btn>

                                </template>
                            </v-tooltip>
                            <v-tooltip v-if="canMakeReal(row)" text="Make this character real, adding it to the scene as an actor.">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="persistCharacter(row.name)" icon="mdi-human-greeting"></v-btn>

                                </template>
                            </v-tooltip>
                            <v-tooltip v-if="row.active" text="Manage character">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="openWorldStateManager('characters', row.name, 'description')" icon="mdi-book-open-page-variant"></v-btn>

                                </template>
                            </v-tooltip>
                            <CharacterKnowledgeHub v-if="row.active && !isPlaythroughActive()" :name="row.name" @open-knowledge="openWorldStateManager('characters', row.name, 'knowledge')" />
                            <v-tooltip v-if="row.active && !isPlaythroughActive()" :text="deactivateTooltip(row.name)">
                                <template v-slot:activator="{ props }">
                                    <v-btn :disabled="busy" :aria-label="deactivateLabel(row.name)" size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="deactivateCharacter($event, row.name)" icon="mdi-exit-run"></v-btn>

                                </template>
                            </v-tooltip>
                            <v-tooltip v-if="characterSuggestions(row.name)" text="Review proposed changes for this character">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" color="highlight5" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="openWorldStateManager('suggestions', 'character-'+row.name)" icon="mdi-lightbulb-on"></v-btn>

                                </template>
                            </v-tooltip>
                        </div>
                        <v-divider class="mt-1"></v-divider>

                        <!-- TRACKED STATES -->

                        <div>
                            <v-tooltip v-for="(state,index) in trackedCharacterStates(row.name)"
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
                                    color="mutedheader"
                                    prepend-icon="mdi-image-auto-adjust"
                                    @click="openWorldStateManager('characters', row.name, 'reinforce', state.question)"
                                    class="mt-1">
                                        {{ state.question }}
                                    </v-chip>
                                </template>
                            </v-tooltip>

                        </div>

                    </v-expansion-panel-text>
                </v-expansion-panel>
            </v-expansion-panels>

            <!-- INACTIVE CHARACTERS -->

            <v-expansion-panels density="compact" v-if="showInactiveCharacters" v-model="inactivePanel">
                <v-expansion-panel rounded="0" density="compact" class="character-section-inactive">
                    <v-expansion-panel-title class="text-title-small" diable-icon-rotate>
                        Inactive ({{ inactiveCharacters.length }})
                        <template v-slot:actions>
                            <span class="knowledge-marker-space"></span>
                            <v-icon icon="mdi-account-off"></v-icon>
                        </template>
                    </v-expansion-panel-title>
                    <Transition name="knowledge-marker">
                        <KnowledgeChangeMarker
                            v-if="inactivePanel !== 0 && inactiveKnowledgeChanges.length"
                            class="active-knowledge-marker"
                            name="inactive characters"
                            action-label="Knowledge changed for inactive characters. Expand Inactive section"
                            :changes="inactiveKnowledgeChanges"
                            @pause="pauseInactiveKnowledge"
                            @open="inactivePanel = 0"
                        />
                    </Transition>
                    <v-expansion-panel-text>
                        <div class="d-flex align-center" v-for="name in inactiveCharacters" :key="name">
                            <span class="text-body-small text-muted">{{ name }}</span>
                            <Transition name="knowledge-marker">
                                <KnowledgeChangeMarker
                                    v-if="knowledgeChanges.has(name)"
                                    :name="name"
                                    :changes="knowledgeChanges.get(name)"
                                    @pause="(reason, paused) => knowledgeNotifications.pause(name, reason, paused)"
                                    @open="openWorldStateManager('characters', name, 'knowledge')"
                                />
                            </Transition>
                            <v-spacer></v-spacer>
                            <CharacterKnowledgeHub :name="name" variant="text" color="secondary" @open-knowledge="openWorldStateManager('characters', name, 'knowledge')" />
                            <v-tooltip :text="activateTooltip(name)">
                                <template v-slot:activator="{ props }">
                                    <v-btn :disabled="busy" :aria-label="activateLabel(name)" size="x-small" color="secondary" v-bind="props" variant="text" density="comfortable" rounded="sm" @click.stop="activateCharacter($event, name)" icon="mdi-human-greeting"></v-btn>
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
                    <v-expansion-panel-title class="text-title-small" diable-icon-rotate>
                        {{ name}}
                        <v-tooltip v-if="obj.manual" :text="manualEntryTooltip">
                            <template v-slot:activator="{ props }">
                                <v-icon v-bind="props" size="x-small" class="ml-1" color="muted">mdi-pin</v-icon>
                            </template>
                        </v-tooltip>
                        <template v-slot:actions>
                            <v-icon icon="mdi-cube"></v-icon>
                        </template>
                    </v-expansion-panel-title>
                            
                    <v-expansion-panel-text class="text-body-medium">
                        {{ obj.snapshot }}
                        <div class="text-center mt-1">
                            <v-tooltip v-if="!isPlaythroughActive()" text="Look at">
                                <template v-slot:activator="{ props }">
                                    <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="lookAtItem(name)" icon="mdi-eye"></v-btn>

                                </template>
                            </v-tooltip>
                            <v-tooltip v-if="obj.snapshot && !isPlaythroughActive()" :text="'Add detail to '+name">
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
                    <v-expansion-panel-title class="text-title-small" diable-icon-rotate>
                        Active Pins ({{ activePins.length }})
                        <template v-slot:actions>
                            <v-icon icon="mdi-pin"></v-icon>
                        </template>
                    </v-expansion-panel-title>
                    <v-expansion-panel-text>
                        <div class="mt-1 text-body-small" v-for="(pin,index) in activePins" :key="index">
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
                    <v-expansion-panel-title class="text-title-small" diable-icon-rotate>
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
                                    color="mutedheader"
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

<WorldStateRefreshDialog ref="refreshDialog" />
</template>

<script>

import WorldStateRefreshDialog from './WorldStateRefreshDialog.vue';
import KnowledgeChangeMarker from './KnowledgeChangeMarker.vue';
import CharacterKnowledgeHub from './CharacterKnowledgeHub.vue';
import { createKnowledgeChanges } from '@/utils/knowledgeChanges';
import VisualAssetsMixin from './VisualAssetsMixin.js';
import {
    dispatchActivateCharacter,
    dispatchDeactivateCharacter,
    dispatchExamineEntity,
    dispatchLookAtEntity,
    isKnownSceneCharacter,
} from '@/utils/entityActions';
import { isPrimaryModifier, primaryModifierLabel } from '@/utils/keyboardModifiers';

const MANUAL_ENTRY_TOOLTIP =
    'Added by hand from a scene message. While the snapshot is durable it never ages out as a '
    + 'stale entry and the item limit never drops it — though it keeps its slot in that limit — '
    + 'until the story drops it, a time jump cuts the scene, or the snapshot is wiped.';

// snapshot.py canonicalizes a key against the actors of the pass that wrote
// it, so most keys arrive canonical - but one written while a character was
// inactive, or before that loop existed, stays raw for good. Claiming is exact
// anyway: a loose claim swallows a real background character's row along with
// its snapshot text and its actions. `mayBeExistingCharacter` carries the
// uncertainty instead, where being wrong only hides a button.
function claimSnapshotKeys(rosterNames, snapshotKeys) {
    const unclaimed = new Map(snapshotKeys.map((key) => [key.toLowerCase(), key]));
    const claimed = new Map();
    for (const rosterName of rosterNames) {
        const lower = rosterName.toLowerCase();
        const key = unclaimed.get(lower);
        if (key === undefined) continue;
        claimed.set(rosterName, key);
        unclaimed.delete(lower);
    }
    return claimed;
}

export default {
    name: 'WorldState',
    components: {
        WorldStateRefreshDialog,
        KnowledgeChangeMarker,
        CharacterKnowledgeHub,
    },
    mixins: [VisualAssetsMixin],
    data() {
        return {
            characters: {},
            suggestions: [],
            items: {},
            location: null,
            requesting: false,
            sceneTime: null,
            reinforce: [],
            activePins: [],
            worldStateMaxHeight: null,
            hasAnyWorldState: false,
            knowledgeChanges: new Map(),
            inactivePanel: null,
            inactiveKnowledgePauses: new Map(),
        }
    },

    props: {
        busy: Boolean,
    },

    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'setWaitingForInput',
        'isInputDisabled',
        'formatWorldStateTemplateString',
        'scene',
        'requestSceneAssets',
        'isPlaythroughActive',
    ],

    emits: [
        'passive-characters',
        'open-world-state-manager'
    ],

    computed: {
        inactiveKnowledgeChanges() {
            return this.inactiveCharacters.flatMap(name =>
                (this.knowledgeChanges.get(name) || []).map(change => ({
                    ...change,
                    target: JSON.stringify([name, change.target]),
                    label: `${name}: ${change.label}`,
                })));
        },
        knowledgeSceneId() {
            return this.sceneData?.data?.id;
        },
        playthroughActive() {
            return this.isPlaythroughActive();
        },
        sceneData() {
            return this.scene ? this.scene() : null;
        },
        assetsMap() {
            return (this.sceneData?.data?.assets?.assets) || {};
        },
        refreshTooltip() {
            return `Update world snapshot (${primaryModifierLabel}+click to add instructions or wipe and start fresh)`;
        },
        inactiveCharacters() {
            return this.sceneData?.data?.inactive_characters || [];
        },
        showInactiveCharacters() {
            return this.inactiveCharacters.length > 0 && !this.isPlaythroughActive();
        },
        rosterNames() {
            return [
                ...(this.sceneData?.data?.characters || []).map((character) => character.name),
                ...this.inactiveCharacters,
            ];
        },
        manualEntryTooltip() {
            return MANUAL_ENTRY_TOOLTIP;
        },
        characterRoster() {
            const snapshot = this.characters || {};
            const keys = Object.keys(snapshot);
            const claimed = claimSnapshotKeys(this.rosterNames, keys);
            const rows = [];
            for (const character of (this.sceneData?.data?.characters || [])) {
                const entry = snapshot[claimed.get(character.name)];
                rows.push({
                    name: character.name,
                    emotion: entry?.emotion || '',
                    snapshot: entry?.snapshot || '',
                    manual: entry?.manual || false,
                    active: true,
                });
            }
            const taken = new Set(claimed.values());
            for (const key of keys) {
                if (taken.has(key)) continue;
                rows.push({
                    name: key,
                    emotion: snapshot[key].emotion,
                    snapshot: snapshot[key].snapshot,
                    manual: snapshot[key].manual || false,
                    active: false,
                });
            }
            return rows;
        },
        // The rows the creative tools menu may offer to introduce. A row whose
        // name overlaps somebody on the roster is not one of them: persist
        // refuses an exact duplicate alone, so introducing "Jason" beside the
        // actor "Jason Smith" adds a second actor for one person. The rows
        // themselves keep their place in the panel either way.
        persistableCharacters() {
            return this.characterRoster
                .filter((row) => !row.active && !this.mayBeExistingCharacter(row.name))
                .map((row) => row.name);
        },
    },

    watch: {
        knowledgeSceneId() {
            this.knowledgeNotifications.clear();
        },
        playthroughActive() {
            this.knowledgeNotifications.clear();
        },
        persistableCharacters: {
            handler(names) {
                this.$emit('passive-characters', names);
            },
            immediate: true,
        },
    },

    methods: {
        canMakeReal(row) {
            return !row.active && !this.mayBeExistingCharacter(row.name) && !this.isPlaythroughActive();
        },
        characterKindTooltip(row) {
            if (row.active) return 'A real character, present in the scene';
            const description = 'Picked up by the world state snapshot, not yet a character.';
            return this.canMakeReal(row) ? `${description} Use Make real to promote.` : description;
        },
        pauseInactiveKnowledge(reason, paused) {
            const names = this.inactiveKnowledgePauses.get(reason) || new Set();
            if (paused) {
                this.inactiveKnowledgePauses.set(reason, names);
                for (const name of this.inactiveCharacters) {
                    if (this.knowledgeChanges.has(name)) names.add(name);
                }
            } else {
                this.inactiveKnowledgePauses.delete(reason);
            }
            for (const name of names) {
                this.knowledgeNotifications.pause(name, `inactive:${reason}`, paused);
            }
        },
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
        activateLabel(name) {
            return `Call ${name} into the scene`;
        },
        deactivateLabel(name) {
            return `Take ${name} out of the scene`;
        },
        activateTooltip(name) {
            return `${this.activateLabel(name)} (${primaryModifierLabel}+click: no narration)`;
        },
        deactivateTooltip(name) {
            return `${this.deactivateLabel(name)} (${primaryModifierLabel}+click: no narration)`;
        },
        activateCharacter(ev, name) {
            dispatchActivateCharacter(this.getWebsocket(), {
                name,
                neverNarrate: isPrimaryModifier(ev),
            });
        },
        deactivateCharacter(ev, name) {
            dispatchDeactivateCharacter(this.getWebsocket(), {
                name,
                neverNarrate: isPrimaryModifier(ev),
            });
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
            this.$refs.refreshDialog.handleClick(event);
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
                if(suggestion.name === name && suggestion.type === 'character' && suggestion.proposals.length > 0) {
                    return true;
                }
            }
            return false;
        },
        characterIsKnown(name) {
            return isKnownSceneCharacter(this.sceneData?.data, name);
        },
        // Same two-way substring test snapshot.py uses to canonicalize a key,
        // asked of the whole roster. Only Make real reads it: persist_character
        // refuses an exact duplicate alone, so offering it for a stale key like
        // "Jason" while "Jason Smith" is on the roster adds a second actor for
        // the same person.
        mayBeExistingCharacter(name) {
            const key = name.toLowerCase();
            return this.rosterNames.some((rosterName) => {
                const roster = rosterName.toLowerCase();
                return roster.includes(key) || key.includes(roster);
            });
        },
        getCharacterAvatar(name) {
            const character = (this.sceneData?.data?.characters || [])
                .find((candidate) => candidate.name === name);
            if (!character) {
                return null;
            }
            return character.current_avatar || character.avatar || null;
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
            for (const row of this.characterRoster) {
                const avatarId = this.getCharacterAvatar(row.name);
                if (avatarId) {
                    avatarIds.push(avatarId);
                }
            }
            if (avatarIds.length > 0) {
                this.loadAssets(avatarIds);
            }
        },

        handleMessage(data) {
            if (data.type === 'knowledge_changed') {
                if (data.data.scene_id === this.knowledgeSceneId && !this.playthroughActive) {
                    this.knowledgeNotifications.add(data.data.changes, this.rosterNames);
                }
                return;
            }
            if ((data.type === 'system' && data.id === 'scene.loaded') ||
                (data.type === 'scene_status' && data.data.restored)) {
                this.knowledgeNotifications.clear();
            }
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
        this.knowledgeNotifications = createKnowledgeChanges((changes) => {
            this.knowledgeChanges = changes;
            if (!changes.size) this.inactiveKnowledgePauses.clear();
            for (const reason of this.inactiveKnowledgePauses.keys()) {
                this.pauseInactiveKnowledge(reason, true);
            }
        });
        this.registerMessageHandler(this.handleMessage);
    },
    beforeUnmount() {
        this.unregisterMessageHandler(this.handleMessage);
        this.knowledgeNotifications.clear();
    },
}
</script>

<style scoped>
.character-row, .character-section-inactive {
    position: relative;
}
.character-row-active > .v-expansion-panel-title {
    border-inline-start: 2px solid rgba(var(--v-theme-primary), 0.65);
    background-color: rgba(var(--v-theme-primary), 0.06);
}
.character-row-background > .v-expansion-panel-title {
    border-inline-start: 2px solid rgba(var(--v-theme-secondary), 0.65);
    background-color: rgba(var(--v-theme-secondary), 0.06);
}
.character-section-inactive > .v-expansion-panel-title {
    border-inline-start: 2px solid rgba(var(--v-theme-mutedheader), 0.45);
    background-color: rgba(var(--v-theme-mutedheader), 0.04);
}
.knowledge-marker-space {
    flex: 0 0 28px;
}
.active-knowledge-marker {
    position: absolute;
    inset-inline-end: 64px;
    top: 12px;
    z-index: 1;
}
.knowledge-marker-leave-active {
    transition: opacity 0.3s ease;
    pointer-events: none;
}
.knowledge-marker-leave-to {
    opacity: 0;
}
@media (prefers-reduced-motion: reduce) {
    .knowledge-marker-leave-active {
        transition: none;
    }
}
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
    border: 2px solid rgb(var(--v-theme-border));
}
</style>
