<template>
    <v-dialog v-model="dialog" scrollable max-width="1400px" min-height="600px">
        <v-overlay contained v-model="isBusy"></v-overlay>
        <v-card>
            <v-card-title><v-icon class="mr-1">mdi-earth</v-icon>World State Manager
                <v-progress-circular v-if="isBusy" indeterminate="disable-shrink" color="primary" size="11"></v-progress-circular>
            </v-card-title>
            <v-tabs color="primary" v-model="tab">
                <v-tab value="characters">
                    <v-icon start>mdi-account-group</v-icon>
                    Characters
                </v-tab>
                <v-tab value="world">
                    <v-icon start>mdi-earth</v-icon>
                    World
                </v-tab>
                <v-tab v-if="historyEnabled" value="history" disabled>
                    <v-icon start>mdi-history</v-icon>
                    History
                </v-tab>
                <v-tab value="contextdb">
                    <v-icon start>mdi-book-open-page-variant</v-icon>
                    Context
                </v-tab>
                <v-tab value="pins">
                    <v-icon start>mdi-pin</v-icon>
                    Pins
                </v-tab>
                <v-tab value="templates">
                    <v-icon start>mdi-cube-scan</v-icon>
                    Templates
                </v-tab>

            </v-tabs>
            <v-window v-model="tab">

                <!-- CHARACTERS -->

                <v-window-item value="characters">
                    <v-card flat>
                        <v-card-text>
                            <v-row>
                                <v-col cols="2">
                                    <v-tabs density="compact" direction="vertical" v-model="selectedCharacter" color="indigo-lighten-3">
                                        <v-tab prepend-icon="mdi-account" v-for="character in characterList.characters" :key="character.name"
                                            @click="loadCharacter(character.name)" :value="character.name">
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
                                </v-col>
                                <v-col cols="10">
                                    <div v-if="selectedCharacter !== null">
                                        <v-card>
                                            <v-card-title>
                                                <v-icon size="small">mdi-account</v-icon>
                                                {{ characterDetails.name }}
                                                <v-chip size="x-small" v-if="characterDetails.is_player === false" color="warning" label>AI</v-chip>
                                                <v-chip size="x-small" v-if="characterDetails.is_player === true" color="info" label>Player</v-chip>
                                                <v-chip size="x-small" class="ml-1" v-if="characterDetails.active === true && characterDetails.is_player === false" color="success" label>Active</v-chip>
                                            
                                                </v-card-title>
                                            <v-divider></v-divider>
                                            <v-tabs v-model="selectedCharacterPage" color="primary" density="compact">
                                                <v-tab value="description">
                                                    <v-icon size="small">mdi-text-account</v-icon>
                                                    Description
                                                </v-tab>
                                                <v-tab value="attributes">
                                                    <v-icon size="small">mdi-format-list-bulleted-type</v-icon>
                                                    Attributes
                                                </v-tab>
                                                <v-tab value="details">
                                                    <v-icon size="small">mdi-format-list-text</v-icon>
                                                    Details
                                                </v-tab>
                                                <v-tab value="reinforce">
                                                    <v-icon size="small">mdi-image-auto-adjust</v-icon>
                                                    States
                                                </v-tab>
                                                <v-tab value="actor">
                                                    <v-icon size="small">mdi-bullhorn</v-icon>
                                                    Actor
                                                </v-tab>
                                            </v-tabs>

                                            <v-card-text>
                                                <!-- CHARACTER DESCRIPTION -->

                                                <div v-if="selectedCharacterPage === 'description'">
                                                    <v-textarea rows="5" auto-grow v-model="characterDetails.description"
                                                        :color="characterDescriptionDirty ? 'info' : ''"
                                                        @update:model-value="queueUpdateCharacterDescription"
                                                        label="Description"
                                                        hint="A short description of the character."></v-textarea>
                                                </div>

                                                <!-- CHARACTER ATTRIBUTES -->

                                                <div v-else-if="selectedCharacterPage === 'attributes'">
                                                    <v-row floating color="grey-darken-5">
                                                        <v-col cols="3">
                                                            <v-text-field v-model="characterAttributeSearch"
                                                                label="Filter attributes" append-inner-icon="mdi-magnify"
                                                                clearable density="compact" variant="underlined"
                                                                class="ml-1 mb-1"
                                                                @update:modelValue="autoSelectFilteredAttribute"></v-text-field>

                                                        </v-col>
                                                        <v-col cols="3"></v-col>
                                                        <v-col cols="2"></v-col>
                                                        <v-col cols="4">
                                                            <v-text-field v-model="newCharacterAttributeName"
                                                                label="New attribute" append-inner-icon="mdi-plus"
                                                                class="mr-1 mb-1" variant="underlined" density="compact"
                                                                @keyup.enter="handleNewCharacterAttribute"
                                                                hint="Attribute name"></v-text-field>

                                                        </v-col>
                                                    </v-row>
                                                    <v-divider></v-divider>
                                                    <v-row>
                                                        <v-col cols="4">
                                                            <v-tabs v-model="selectedCharacterAttribute" density="compact" direction="vertical" color="indigo-lighten-3">
                                                                <v-tab density="compact" v-for="(value, attribute) in filteredCharacterAttributes()"
                                                                class="text-caption"
                                                                    :key="attribute" 
                                                                    :value="attribute">
                                                                    {{ attribute }}
                                                                </v-tab>
                                                            </v-tabs>
                                                        </v-col>
                                                        <v-col cols="8">
                                                            <div v-if="selectedCharacterAttribute !== null">

                                                                <ContextualGenerate 
                                                                    :context="'character attribute:'+selectedCharacterAttribute" 

                                                                    :original="characterDetails.base_attributes[selectedCharacterAttribute]"

                                                                    :character="characterDetails.name"

                                                                    @generate="content => setAndUpdateCharacterAttribute(selectedCharacterAttribute, content)"
                                                                />

                                                                <v-textarea ref="characterAttribute" rows="5" auto-grow
                                                                    :label="selectedCharacterAttribute"
                                                                    :color="characterAttributeDirty ? 'info' : ''"

                                                                    @update:modelValue="queueUpdateCharacterAttribute(selectedCharacterAttribute)"

                                                                    v-model="characterDetails.base_attributes[selectedCharacterAttribute]">
                                                                    

                                                                </v-textarea>

                                                            </div>
                                                            <v-row v-if="selectedCharacterAttribute !== null">
                                                                <v-col cols="12">
                                                                    <v-btn v-if="removeCharacterAttributeConfirm === false"
                                                                        rounded="sm" prepend-icon="mdi-close-box-outline" color="error"
                                                                        variant="text"
                                                                        @click.stop="removeCharacterAttributeConfirm = true">
                                                                        Remove attribute
                                                                    </v-btn>
                                                                    <div v-else>
                                                                        <v-btn rounded="sm" prepend-icon="mdi-close-box-outline"
                                                                            @click.stop="deleteCharacterAttribute(selectedCharacterAttribute)"
                                                                            color="error" variant="text">
                                                                            Confirm removal
                                                                        </v-btn>
                                                                        <v-btn class="ml-1" rounded="sm"
                                                                            prepend-icon="mdi-cancel"
                                                                            @click.stop="removeCharacterAttributeConfirm = false"
                                                                            color="info" variant="text">
                                                                            Cancel
                                                                        </v-btn>
                                                                    </div>

                                                                </v-col>
                                                            </v-row>
                                                        </v-col>
                                                    </v-row>
                                                </div>

                                                <!-- CHARACTER DETAILS -->

                                                <div v-else-if="selectedCharacterPage === 'details'">
                                                    <v-row floating color="grey-darken-5">
                                                        <v-col cols="3">
                                                            <v-text-field v-model="characterDetailSearch"
                                                                label="Filter details" append-inner-icon="mdi-magnify"
                                                                clearable density="compact" variant="underlined"
                                                                class="ml-1 mb-1"
                                                                @update:modelValue="autoSelectFilteredDetail"></v-text-field>
                                                        </v-col>
                                                        <v-col cols="3"></v-col>
                                                        <v-col cols="2"></v-col>
                                                        <v-col cols="4">
                                                            <v-text-field v-model="newCharacterDetailName"
                                                                label="New detail" append-inner-icon="mdi-plus"
                                                                class="mr-1 mb-1" variant="underlined" density="compact"
                                                                @keyup.enter="handleNewCharacterDetail"
                                                                hint="Descriptive name or question."></v-text-field>
                                                        </v-col>
                                                    </v-row>
                                                    <v-divider></v-divider>
                                                    <v-row>
                                                        <v-col cols="4">
                                                            <v-tabs direction="vertical" density="compact" v-model="selectedCharacterDetail" color="indigo-lighten-3">
                                                                <v-tab v-for="(value, detail) in filteredCharacterDetails()"
                                                                    :key="detail"
                                                                    class="text-caption"
                                                                    :value="detail">
                                                                    <v-list-item-title class="text-caption">{{ detail
                                                                    }}</v-list-item-title>
                                                                </v-tab>
                                                            </v-tabs>
                                                        </v-col>
                                                        <v-col cols="8">
                                                            <div v-if="selectedCharacterDetail">

                                                                <ContextualGenerate 
                                                                    :context="'character detail:'+selectedCharacterDetail" 

                                                                    :original="characterDetails.details[selectedCharacterDetail]"

                                                                    :character="characterDetails.name"

                                                                    @generate="content => setAndUpdateCharacterDetail(selectedCharacterDetail, content)"
                                                                />


                                                                <v-textarea rows="5" max-rows="10" auto-grow
                                                                    ref="characterDetail"
                                                                    :color="characterDetailDirty ? 'info' : ''"
                                                                    @update:modelValue="queueUpdateCharacterDetail(selectedCharacterDetail)"
                                                                    :label="selectedCharacterDetail"
                                                                    v-model="characterDetails.details[selectedCharacterDetail]">
                                                                </v-textarea>


                                                            </div>

                                                            <v-row v-if="selectedCharacterDetail">
                                                                <v-col cols="6">
                                                                    <v-btn v-if="removeCharacterDetailConfirm === false"
                                                                        rounded="sm" prepend-icon="mdi-close-box-outline" color="error"
                                                                        variant="text"
                                                                        @click.stop="removeCharacterDetailConfirm = true">
                                                                        Remove detail
                                                                    </v-btn>
                                                                    <div v-else>
                                                                        <v-btn rounded="sm" prepend-icon="mdi-close-box-outline"
                                                                            @click.stop="deleteCharacterDetail(selectedCharacterDetail)"
                                                                            color="error" variant="text">
                                                                            Confirm removal
                                                                        </v-btn>
                                                                        <v-btn class="ml-1" rounded="sm"
                                                                            prepend-icon="mdi-cancel"
                                                                            @click.stop="removeCharacterDetailConfirm = false"
                                                                            color="info" variant="text">
                                                                            Cancel
                                                                        </v-btn>
                                                                    </div>

                                                                </v-col>
                                                                <v-col cols="6" class="text-right">
                                                                    <div
                                                                        v-if="characterDetails.reinforcements[selectedCharacterDetail]">
                                                                        <v-btn rounded="sm"
                                                                            prepend-icon="mdi-image-auto-adjust"
                                                                            @click.stop="viewCharacterStateReinforcer(selectedCharacterDetail)"
                                                                            color="primary" variant="text">
                                                                            Manage auto state
                                                                        </v-btn>
                                                                    </div>
                                                                    <div v-else>
                                                                        <v-btn rounded="sm"
                                                                            prepend-icon="mdi-image-auto-adjust"
                                                                            @click.stop="viewCharacterStateReinforcer(selectedCharacterDetail)"
                                                                            color="primary" variant="text">
                                                                            Setup auto state
                                                                        </v-btn>
                                                                    </div>
                                                                </v-col>
                                                            </v-row>

                                                        </v-col>
                                                    </v-row>
                                                </div>

                                                <!-- CHARACTER STATE REINFORCERS -->

                                                <div v-else-if="selectedCharacterPage === 'reinforce'">

                                                    <v-row floating color="grey-darken-5">
                                                        <v-col cols="3">
                                                            <v-text-field v-model="characterStateReinforcerSearch"
                                                                label="Filter states" append-inner-icon="mdi-magnify"
                                                                clearable density="compact" variant="underlined"
                                                                class="ml-1 mb-1"
                                                                @update:modelValue="autoSelectFilteredStateReinforcer"></v-text-field>

                                                        </v-col>
                                                        <v-col cols="3"></v-col>
                                                        <v-col cols="2"></v-col>
                                                        <v-col cols="4">
                                                            <v-text-field v-model="newCharacterStateReinforcerQuestion"
                                                                label="New state" append-inner-icon="mdi-plus"
                                                                class="mr-1 mb-1" variant="underlined" density="compact"
                                                                @keyup.enter="handleNewCharacterStateReinforcer"
                                                                hint="Question or attribute name."></v-text-field>
                                                        </v-col>
                                                    </v-row>
                                                    <v-divider></v-divider>
                                                    <v-row>
                                                        <v-col cols="4">
                                                            <v-list density="compact">

                                                                <!-- add from template -->
                                                                <div v-if="characterStateTemplatesAvailable()">
                                                                    <v-list-item density="compact"
                                                                        @click.stop="showCharacterStateTemplates = !showCharacterStateTemplates"
                                                                        prepend-icon="mdi-cube-scan" color="info">
                                                                        <v-list-item-title>
                                                                            Templates
                                                                            <v-progress-circular class="ml-1 mr-3" size="14"
                                                                                indeterminate="disable-shrink" color="primary"
                                                                                v-if="characterStateTemplateBusy"></v-progress-circular>
                                                                        </v-list-item-title>
                                                                    </v-list-item>
                                                                    <div v-if="showCharacterStateTemplates">
                                                                        <v-list-item density="compact"
                                                                            @click.stop="addCharacterStateFromTemplate(template, characterDetails.name)"
                                                                            v-for="(template, index) in characterStateTemplates()"
                                                                            :key="index" prepend-icon="mdi-cube-scan"
                                                                            :disabled="characterStateTemplateBusy">
                                                                            <v-list-item-title>{{ template.name
                                                                            }}</v-list-item-title>
                                                                            <v-list-item-subtitle>{{ template.description
                                                                            }}</v-list-item-subtitle>
                                                                        </v-list-item>
                                                                    </div>
                                                                    <v-divider></v-divider>
                                                                </div>

                                                            </v-list>
                                                            <v-tabs v-model="selectedCharacterStateReinforcer" direction="vertical" color="indigo-lighten-3" density="compact">
                                                                <v-tab v-for="(value, detail) in filteredCharacterStateReinforcers()"
                                                                    :key="detail"
                                                                    class="text-caption"
                                                                    :value="detail">
                                                                    <div class="text-left">{{ detail }}<div><v-chip size="x-small" label variant="outlined"
                                                                            color="info">update in {{ value.due }}
                                                                            turns</v-chip>
                                                                        </div>
                                                                    </div>
                                                                </v-tab>
                                                            </v-tabs>
                                                        </v-col>
                                                        <v-col cols="8">
                                                            <div v-if="selectedCharacterStateReinforcer">
                                                                <v-textarea rows="5" auto-grow max-rows="15"
                                                                    :label="selectedCharacterStateReinforcer"
                                                                    v-model="characterDetails.reinforcements[selectedCharacterStateReinforcer].answer"
                                                                    @update:modelValue="queueUpdateCharacterStateReinforcement(selectedCharacterStateReinforcer)"
                                                                    :color="characterStateReinforcerDirty ? 'info' : ''"></v-textarea>

                                                                <v-row>
                                                                    <v-col cols="6">
                                                                        <v-text-field
                                                                            v-model="characterDetails.reinforcements[selectedCharacterStateReinforcer].interval"
                                                                            label="Re-inforce / Update detail every N turns"
                                                                            type="number" min="1" max="100" step="1"
                                                                            class="mb-2"
                                                                            @update:modelValue="queueUpdateCharacterStateReinforcement(selectedCharacterStateReinforcer)"
                                                                            :color="characterStateReinforcerDirty ? 'info' : ''"></v-text-field>
                                                                    </v-col>
                                                                    <v-col cols="6">
                                                                        <v-select
                                                                            v-model="characterDetails.reinforcements[selectedCharacterStateReinforcer].insert"
                                                                            :items="insertionModes"
                                                                            label="Context Attachment Method"
                                                                            class="mr-1 mb-1" variant="underlined"
                                                                            density="compact"
                                                                            @update:modelValue="queueUpdateCharacterStateReinforcement(selectedCharacterStateReinforcer)"
                                                                            :color="characterStateReinforcerDirty ? 'info' : ''">
                                                                        </v-select>
                                                                    </v-col>
                                                                </v-row>



                                                                <v-textarea rows="3" auto-grow max-rows="5"
                                                                    label="Additional instructions to the AI for generating this state."
                                                                    v-model="characterDetails.reinforcements[selectedCharacterStateReinforcer].instructions"
                                                                    @update:modelValue="queueUpdateCharacterStateReinforcement(selectedCharacterStateReinforcer)"
                                                                    :color="characterStateReinforcerDirty ? 'info' : ''"></v-textarea>

                                                                <v-row>
                                                                    <v-col cols="6">
                                                                        <div
                                                                            v-if="removeCharacterStateReinforcerConfirm === false">
                                                                            <v-btn rounded="sm" prepend-icon="mdi-close-box-outline"
                                                                                color="error" variant="text"
                                                                                @click.stop="removeCharacterStateReinforcerConfirm = true">
                                                                                Remove state
                                                                            </v-btn>
                                                                        </div>
                                                                        <div v-else>
                                                                            <v-btn rounded="sm" prepend-icon="mdi-close-box-outline"
                                                                                @click.stop="deleteCharacterStateReinforcement(selectedCharacterStateReinforcer)"
                                                                                color="error" variant="text">
                                                                                Confirm removal
                                                                            </v-btn>
                                                                            <v-btn class="ml-1" rounded="sm"
                                                                                prepend-icon="mdi-cancel"
                                                                                @click.stop="removeCharacterStateReinforcerConfirm = false"
                                                                                color="info" variant="text">
                                                                                Cancel
                                                                            </v-btn>
                                                                        </div>
                                                                    </v-col>
                                                                    <v-col cols="6" class="text-right flex">
                                                                        <v-btn rounded="sm" prepend-icon="mdi-refresh"
                                                                            @click.stop="runCharacterStateReinforcement(selectedCharacterStateReinforcer)"
                                                                            color="primary" variant="text">
                                                                            Refresh State
                                                                        </v-btn>
                                                                        <v-tooltip
                                                                            text="Removes all previously generated reinforcements for this state and then regenerates it">
                                                                            <template v-slot:activator="{ props }">
                                                                                <v-btn
                                                                                    v-if="resetCharacterStateReinforcerConfirm === true"
                                                                                    v-bind="props" rounded="sm"
                                                                                    prepend-icon="mdi-backup-restore"
                                                                                    @click.stop="runCharacterStateReinforcement(selectedCharacterStateReinforcer, true)"
                                                                                    color="warning" variant="text">
                                                                                    Confirm Reset State
                                                                                </v-btn>
                                                                                <v-btn v-else v-bind="props" rounded="sm"
                                                                                    prepend-icon="mdi-backup-restore"
                                                                                    @click.stop="resetCharacterStateReinforcerConfirm = true"
                                                                                    color="warning" variant="text">
                                                                                    Reset State
                                                                                </v-btn>
                                                                            </template>
                                                                        </v-tooltip>
                                                                    </v-col>
                                                                </v-row>
                                                            </div>
                                                        </v-col>
                                                    </v-row>
                                                </div>

                                                <!-- CHARACTER ACTOR -->

                                                <div v-else-if="selectedCharacterPage === 'actor'">
                                                    <WorldStateManagerCharacterActor ref="actor" :character="characterDetails" />
                                                </div>
                                            </v-card-text>
                                        </v-card>



                                    </div>
                                    <v-alert v-else type="info" color="grey" variant="text" icon="mdi-account">
                                        Manage character attributes and add extra details.
                                        <br><br>
                                        You can also set up automatic reinforcement of character states. This will cause the
                                        AI to regularly re-evaluate the state and update the detail accordingly.
                                        <br><br>
                                        Select a character from the list on the left to get started.
                                    </v-alert>
                                </v-col>
                            </v-row>
                        </v-card-text>
                    </v-card>
                </v-window-item>

                <!-- WORLD -->

                <v-window-item value="world">
                    <WorldStateManagerWorld ref="world" />
                </v-window-item>

                <!-- HISTORY -->

                <v-window-item value="history">
                    <v-card flat>
                        <v-card-text>
                            <div>
                                <!-- Placeholder for History content -->
                            </div>
                        </v-card-text>
                    </v-card>
                </v-window-item>

                <!-- CONTEXT DB -->

                <v-window-item value="contextdb">
                    <v-card flat>
                        <v-card-text>
                            <v-toolbar floating density="compact" class="mb-2" color="grey-darken-4">
                                <v-text-field v-model="contextDBQuery" label="Content search"
                                    append-inner-icon="mdi-magnify" clearable single-line hide-details density="compact"
                                    variant="underlined" class="ml-1 mb-1 mr-1"
                                    @keyup.enter="queryContextDB"></v-text-field>

                                <v-select v-model="contextDBQueryMetaKey" :items="contextDBMetaKeys" label="Filter By Tag"
                                    class="mr-1 mb-1" variant="underlined" single-line hide-details
                                    density="compact"></v-select>
                                <v-select
                                    v-if="contextDBQueryMetaKey !== null && contextDBMetaValuesByType[contextDBQueryMetaKey]"
                                    v-model="contextDBQueryMetaValue"
                                    :items="contextDBMetaValuesByType[contextDBQueryMetaKey]()" label="Tag value"
                                    class="mr-1 mb-1" variant="underlined" single-line hide-details
                                    density="compact"></v-select>
                                <v-text-field v-else v-model="contextDBQueryMetaValue" label="Tag value" class="mr-1 mb-1"
                                    variant="underlined" single-line hide-details density="compact"></v-text-field>
                                <v-spacer></v-spacer>
                                <!-- button that opens the tools menu -->
                                <v-menu>
                                    <template v-slot:activator="{ props }">
                                        <v-btn rounded="sm" v-bind="props" prepend-icon="mdi-tools" variant="text">
                                            Tools
                                        </v-btn>
                                    </template>
                                    <v-list>
                                        <v-list-item @click.stop="resetContextDB" append-icon="mdi-shield-alert">
                                            <v-list-item-title>Reset</v-list-item-title>
                                        </v-list-item>
                                    </v-list>
                                </v-menu>

                                <!-- button to open add content db entry dialog -->
                                <v-btn rounded="sm" prepend-icon="mdi-plus" @click.stop="dialogAddContextDBEntry = true"
                                    variant="text">
                                    Add entry
                                </v-btn>
                            </v-toolbar>
                            <v-divider></v-divider>
                            <!-- add entry-->
                            <v-card v-if="dialogAddContextDBEntry === true">
                                <v-card-title>
                                    Add entry
                                </v-card-title>
                                <v-card-text>
                                    <v-row>
                                        <v-col cols="12">
                                            <v-textarea rows="5" auto-grow v-model="newContextDBEntryText" label="Content"
                                                hint="The content of the entry."></v-textarea>
                                        </v-col>
                                    </v-row>
                                    <v-row>
                                        <v-col cols="12">
                                            <v-chip v-for="(value, name) in newContextDBEntryMeta" :key="name" label
                                                size="x-small" variant="outlined" class="ml-1" closable
                                                @click:close="handleRemoveContextDBEntryMeta(name)">{{ name }}: {{ value
                                                }}</v-chip>
                                        </v-col>
                                    </v-row>
                                    <v-row>
                                        <v-col cols="3">
                                            <v-select v-model="newContextDBEntryMetaKey" :items="contextDBMetaKeys"
                                                label="Meta key" class="mr-1 mb-1" variant="underlined" single-line
                                                hide-details density="compact"></v-select>
                                        </v-col>
                                        <v-col cols="3">
                                            <v-select
                                                v-if="newContextDBEntryMetaKey !== null && contextDBMetaValuesByType[newContextDBEntryMetaKey]"
                                                v-model="newContextDBEntryMetaValue"
                                                :items="contextDBMetaValuesByType[newContextDBEntryMetaKey]()"
                                                label="Meta value" class="mr-1 mb-1" variant="underlined" single-line
                                                hide-details density="compact"></v-select>
                                            <v-text-field v-else v-model="newContextDBEntryMetaValue" label="Meta value"
                                                class="mr-1 mb-1" variant="underlined" single-line hide-details
                                                density="compact"></v-text-field>
                                        </v-col>
                                        <v-col cols="3">
                                            <v-btn rounded="sm" color="primary" prepend-icon="mdi-plus"
                                                @click.stop="handleNewContextDBEntryMeta" variant="text">
                                                Add meta
                                            </v-btn>
                                        </v-col>
                                    </v-row>
                                </v-card-text>
                                <v-card-actions>
                                    <!-- cancel -->
                                    <v-btn rounded="sm" prepend-icon="mdi-cancel"
                                        @click.stop="dialogAddContextDBEntry = false" color="info" variant="text">
                                        Cancel
                                    </v-btn>
                                    <v-spacer></v-spacer>
                                    <!-- add -->
                                    <v-btn rounded="sm" prepend-icon="mdi-plus" @click.stop="addContextDBEntry"
                                        color="primary" variant="text">
                                        Add
                                    </v-btn>
                                </v-card-actions>
                            </v-card>

                            <!-- results -->
                            <div v-else>
                                <v-table height="600px" v-if="contextDB.entries.length > 0">
                                    <thead>
                                        <tr>
                                            <th class="text-left"></th>
                                            <th class="text-left" width="60%">Content</th>
                                            <th class="text-center">Pin</th>
                                            <th class="text-left">Tags</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr v-for="entry in contextDB.entries" :key="entry.id">
                                            <td>
                                                <!-- remove -->
                                                <v-tooltip text="Delete entry">
                                                    <template v-slot:activator="{ props }">
                                                        <v-btn icon size="x-small" v-bind="props" rounded="sm"
                                                            variant="text" color="red-darken-1"
                                                            @click.stop="deleteContextDBEntry(entry.id)">
                                                            <v-icon>mdi-close-box-outline</v-icon>
                                                        </v-btn>
                                                    </template>
                                                </v-tooltip>
                                            </td>
                                            <td>
                                                <v-textarea rows="1" auto-grow density="compact" hide-details
                                                    :color="entry.dirty ? 'info' : ''" v-model="entry.text"
                                                    @update:model-value="queueUpdateContextDBEntry(entry)"></v-textarea>
                                            </td>
                                            <td class="text-center">
                                                <v-tooltip :text="entryHasPin(entry.id) ? 'Manage pin' : 'Add pin'">
                                                    <template v-slot:activator="{ props }">
                                                        <v-btn v-bind="props" size="x-small" rounded="sm" variant="text"
                                                            v-if="entryIsPinned(entry.id)" color="success" icon
                                                            @click.stop="selectPin(entry.id)"><v-icon>mdi-pin</v-icon></v-btn>
                                                        <v-btn v-bind="props" size="x-small" rounded="sm" variant="text"
                                                            v-else-if="entryHasPin(entry.id)" color="red-darken-2" icon
                                                            @click.stop="selectPin(entry.id)"><v-icon>mdi-pin</v-icon></v-btn>
                                                        <v-btn v-bind="props" size="x-small" rounded="sm" variant="text"
                                                            v-else color="grey-lighten-2" icon
                                                            @click.stop="addPin(entry.id)"><v-icon>mdi-pin</v-icon></v-btn>
                                                    </template>
                                                </v-tooltip>

                                            </td>
                                            <td>
                                                <!-- render entry.meta as v-chip elements showing both name and value -->
                                                <v-chip v-for="(value, name) in visibleMetaTags(entry.meta)" :key="name"
                                                    label size="x-small" variant="outlined" class="ml-1">{{ name }}: {{
                                                        value }}</v-chip>
                                            </td>
                                        </tr>
                                    </tbody>
                                </v-table>
                                <v-alert v-else-if="contextDBCurrentQuery" dense type="warning" variant="text"
                                    icon="mdi-information-outline">
                                    No results
                                </v-alert>
                                <v-alert v-else dense type="info" variant="text" icon="mdi-magnify">
                                    Enter a query to search the context database.
                                </v-alert>
                            </div>

                        </v-card-text>
                    </v-card>
                </v-window-item>

                <!-- PINS -->

                <v-window-item value="pins">
                    <v-card flat>
                        <v-card-text>
                            <v-row>
                                <v-col cols="3">
                                    <v-list dense v-if="pinsExist()">
                                        <v-list-item prepend-icon="mdi-help" @click.stop="selectedPin = null">
                                            <v-list-item-title>Information</v-list-item-title>
                                        </v-list-item>
                                        <v-list-item v-for="pin in pins" :key="pin.pin.entry_id"
                                            @click.stop="selectedPin = pin"
                                            :prepend-icon="pin.pin.active ? 'mdi-pin' : 'mdi-pin-off'"
                                            :class="pin.pin.active ? '' : 'inactive'">
                                            <v-list-item-title>{{ pin.text }}</v-list-item-title>
                                            <v-list-item-subtitle>

                                            </v-list-item-subtitle>
                                        </v-list-item>
                                    </v-list>
                                    <v-card v-else>
                                        <v-card-text>
                                            No pins defined.
                                        </v-card-text>
                                    </v-card>
                                </v-col>
                                <v-col cols="9">
                                    <v-row v-if="selectedPin !== null">
                                        <v-col cols="7">
                                            <v-card>
                                                <v-checkbox hide-details dense v-model="selectedPin.pin.active"
                                                    label="Pin active" @change="updatePin(selectedPin)"></v-checkbox>
                                                <v-alert class="mb-2 pre-wrap" variant="text" color="grey"
                                                    icon="mdi-book-open-page-variant">
                                                    {{ selectedPin.text }}

                                                </v-alert>
                                                <v-card-actions>
                                                    <v-btn v-if="removePinConfirm === false" rounded="sm"
                                                        prepend-icon="mdi-close-box-outline" color="error" variant="text"
                                                        @click.stop="removePinConfirm = true">
                                                        Remove Pin
                                                    </v-btn>
                                                    <span v-else>
                                                        <v-btn rounded="sm" prepend-icon="mdi-close-box-outline"
                                                            @click.stop="removePin(selectedPin.pin.entry_id)" color="error"
                                                            variant="text">
                                                            Confirm removal
                                                        </v-btn>
                                                        <v-btn class="ml-1" rounded="sm" prepend-icon="mdi-cancel"
                                                            @click.stop="removePinConfirm = false" color="info"
                                                            variant="text">
                                                            Cancel
                                                        </v-btn>
                                                    </span>
                                                    <v-spacer></v-spacer>
                                                    <v-btn variant="text" color="primary"
                                                        @click.stop="loadContextDBEntry(selectedPin.pin.entry_id)"
                                                        prepend-icon="mdi-book-open-page-variant">View in context DB</v-btn>
                                                </v-card-actions>
                                            </v-card>
                                        </v-col>
                                        <v-col cols="5">
                                            <v-card>
                                                <v-card-title><v-icon size="small">mdi-robot</v-icon> Conditional auto
                                                    pinning</v-card-title>
                                                <v-card-text>
                                                    <v-textarea rows="1" auto-grow v-model="selectedPin.pin.condition"
                                                        label="Condition question prompt for auto pinning"
                                                        hint="The condition that must be met for the pin to be active. Prompt will be evaluated by the AI (World State agent) regularly. This should be a question that the AI can answer with a yes or no."
                                                        @update:model-value="queueUpdatePin(selectedPin)">
                                                    </v-textarea>
                                                    <v-checkbox hide-details dense v-model="selectedPin.pin.condition_state"
                                                        label="Current condition evaluation"
                                                        @change="updatePin(selectedPin)"></v-checkbox>
                                                </v-card-text>
                                            </v-card>
                                        </v-col>


                                    </v-row>
                                    <v-alert v-else type="info" color="grey" variant="text" icon="mdi-pin">
                                        Pins allow you to permanently pin a context entry to the AI context. While a pin is
                                        active, the AI will always consider the pinned entry when generating text. <v-icon
                                            color="warning">mdi-alert</v-icon> Pinning too many entries may use up your
                                        available context size, so use them wisely.

                                        <br><br>
                                        Additionally you may also define auto pin conditions that the World State agent will
                                        check every turn. If the condition is met, the entry will be pinned. If the
                                        condition
                                        is no longer met, the entry will be unpinned.

                                        <br><br>
                                        Finally, remember there is also automatic insertion of context based on relevance to
                                        the current scene progress, which happens regardless of pins. Pins are just a way to
                                        ensure that a specific entry is always considered relevant.

                                        <br><br>
                                        <v-btn color="primary" variant="text" prepend-icon="mdi-plus"
                                            @click.stop="tab = 'contextdb'">Add new pins through the context
                                            manager.</v-btn>

                                    </v-alert>

                                </v-col>
                            </v-row>
                        </v-card-text>
                    </v-card>
                </v-window-item>

                <!-- TEMPLATES -->
                <v-window-item value="templates">
                    <WorldStateManagerTemplates ref="templates" />
                </v-window-item>

            </v-window>
            <v-card-actions>
                <v-spacer></v-spacer>
                <!-- Placeholder for any actions -->
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import WorldStateManagerTemplates from './WorldStateManagerTemplates.vue';
import WorldStateManagerWorld from './WorldStateManagerWorld.vue';
import WorldStateManagerCharacterActor from './WorldStateManagerCharacterActor.vue';
import ContextualGenerate from './ContextualGenerate.vue';

export default {
    name: 'WorldStateManager',
    components: {
        WorldStateManagerTemplates,
        WorldStateManagerWorld,
        WorldStateManagerCharacterActor,
        ContextualGenerate,
    },
    computed: {
        characterStateReinforcementsList() {
            let list = [];
            for (let reinforcement in this.characterDetails.reinforcements) {
                list.push(this.characterDetails.reinforcements[reinforcement]);
            }
            return list;
        },
    },
    data() {
        return {
            // general
            tab: 'characters',
            dialog: false,
            requireSceneSave: false,
            isBusy: false,
            historyEnabled: false,
            insertionModes: [
                { "title": "Passive", "value": "never", "props": { "subtitle": "Rely on pins and relevancy attachment" } },
                { "title": "Sequential", "value": "sequential", "props": { "subtitle": "Insert into current scene progression" } },
                { "title": "Conversation Context", "value": "conversation-context", "props": { "subtitle": "Insert into conversation context for this character" } },
                { "title": "All context", "value": "all-context", "props": { "subtitle": "Insert into all context" } },
            ],
            deferedNavigation: null,
            templates: {
                state_reinforcement: {},
            },

            // characters
            selectedCharacter: null,
            selectedCharacterPage: 'description',
            selectedCharacterAttribute: null,
            selectedCharacterDetail: null,
            selectedCharacterStateReinforcer: null,

            newCharacterAttributeName: null,
            newCharacterAttributeValue: null,

            newCharacterDetailName: null,
            newCharacterDetailValue: null,

            newCharacterStateReinforcerInterval: 10,
            newCharacterStateReinforcerInstructions: "",
            newCharacterStateReinforcerQuestion: null,
            newCharacterStateReinforcerInsert: "sequential",

            removeCharacterAttributeConfirm: false,
            removeCharacterDetailConfirm: false,
            removeCharacterStateReinforcerConfirm: false,
            resetCharacterStateReinforcerConfirm: false,

            characterAttributeSearch: null,
            characterDetailSearch: null,
            characterStateReinforcerSearch: null,

            characterAttributeDirty: false,
            characterDetailDirty: false,
            characterDescriptionDirty: false,
            characterStateReinforcerDirty: false,

            characterAttributeUpdateTimeout: null,
            characterDetailUpdateTimeout: null,
            characterDescriptionUpdateTimeout: null,
            contextDBEntryUpdateTimeout: null,

            characterDetailReinforceInterval: 10,
            characterDetailReinforceIntructions: "",

            characterStateTemplateBusy: false,
            showCharacterStateTemplates: false,

            characterList: {
                characters: [],
            },
            characterDetails: {},

            // world

            worldContext: {},

            // history

            // context db

            contextDBQuery: null,
            contextDBQueryMetaKey: null,
            contextDBQueryMetaValue: null,
            contextDBCurrentQuery: null,
            contextDB: { entries: [] },
            contextDBMetaKeys: [
                "character",
                "typ",
                "ts",
                "detail",
                "item",
            ],
            contextDBMetaValuesByType: {
                character: () => {
                    let list = Object.keys(this.characterList.characters);
                    list.push("__narrator__");
                    return list;
                },
                typ: () => {
                    return ["base_attribute", "details", "history", "world_state", "lore"]
                },
            },

            selectedContextDBEntry: null,
            dialogAddContextDBEntry: false,

            newContextDBEntryText: null,
            newContextDBEntryMetaKey: null,
            newContextDBEntryMetaValue: null,
            newContextDBEntryMeta: {},

            // pins

            pins: {},
            selectedPin: null,
            pinUpdateTimeout: null,
            removePinConfirm: false,


        }
    },
    watch: {
        dialog(val) {
            if (val === false) {
                this.saveOnExit();
            }
        },
        tab(val) {
            if (val === 'templates') {
                this.$nextTick(() => {
                    this.$refs.templates.requestTemplates();
                });
            }
        },
        characterDetails() {
            if (this.deferedNavigation !== null) {
                if (this.deferedNavigation[0] === 'characters') {
                    this.selectedCharacter = this.deferedNavigation[1];
                    this.selectedCharacterPage = this.deferedNavigation[2];
                    if (this.deferedNavigation[2] == 'attributes') {
                        this.selectedCharacterAttribute = this.deferedNavigation[3];
                    }
                    else if (this.deferedNavigation[2] == 'details') {
                        this.selectedCharacterDetail = this.deferedNavigation[3];
                    }
                    else if (this.deferedNavigation[2] == 'reinforce') {
                        this.selectedCharacterStateReinforcer = this.deferedNavigation[3];
                    }
                }
                this.deferedNavigation = null;
            }
        }
    },
    provide() {
        return {
            insertionModes: this.insertionModes,
            pins: this.pins,
            addPin: this.addPin,
            entryHasPin: this.entryHasPin,
            selectPin: this.selectPin,
            loadContextDBEntry: this.loadContextDBEntry,
            requestTemplates: this.requestTemplates,
        }
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
        show(tab, sub1, sub2, sub3) {
            this.reset();
            this.requestCharacterList();
            this.requestPins();
            this.requestTemplates();

            this.dialog = true;
            if (tab) {
                this.tab = tab;
            }
            if (tab == 'characters') {
                if (sub1 != null) {
                    this.$nextTick(() => {
                        this.loadCharacter(sub1);
                        this.deferedNavigation = ['characters', sub1, sub2, sub3];
                    });
                }
            }
            else if (tab == 'pins') {
                if (sub1 != null) {
                    this.selectedPin = this.pins[sub1];
                }
            }
            else if (tab == 'world') {
                if (sub1 != null) {
                    this.$nextTick(() => {
                        this.$refs.world.navigate(sub1, sub2, sub3);
                    });
                }
            }
        },
        reset() {
            this.characterList = {
                characters: [],
            };
            this.characterDetails = {};
            this.pins = {};
            this.contextDB = { entries: [] };
            this.selectedCharacter = null;
            this.deferSelectedCharacter = null;
            this.selectedCharacterPage = 'description';
            this.selectedCharacterAttribute = null;
            this.selectedCharacterDetail = null;
            this.selectedCharacterStateReinforcer = null;
            this.selectedContextDBEntry = null;
            this.newCharacterAttributeName = null;
            this.newCharacterAttributeValue = null;
            this.newCharacterDetailName = null;
            this.newCharacterDetailValue = null;
            this.removeCharacterAttributeConfirm = false;
            this.removeCharacterDetailConfirm = false;
            this.resetCharacterStateReinforcerConfirm = false;
            this.characterAttributeSearch = null;
            this.characterDetailSearch = null;
            this.newCharacterStateReinforcerInterval = 10;
            this.newCharacterStateReinforcerInstructions = "";
            this.newCharacterStateReinforcerQuestion = null;
            this.newCharacterStateReinforcerInsert = "sequential";
            this.characterAttributeDirty = false;
            this.characterDetailDirty = false;
            this.characterDescriptionDirty = false;
            this.characterStateReinforcerDirty = false;
            this.characterStateTemplateBusy = false;
            this.showCharacterStateTemplates = false;
            this.contextDBCurrentQuery = null;
            this.contextDBQuery = null;
            this.contextDBQueryMetaKey = null;
            this.contextDBQueryMetaValue = null;
            this.newContextDBEntryMeta = {};
            this.newContextDBEntryText = null;
            this.newContextDBEntryMetaKey = null;
            this.newContextDBEntryMetaValue = null;
            this.dialogAddContextDBEntry = false;
            this.selectedPin = null;
            this.pinUpdateTimeout = null;
            this.removePinConfirm = false;
            this.deferedNavigation = null;
            this.isBusy = false;
        },
        exit() {
            this.dialog = false;
        },
        saveOnExit() {
            if (!this.requireSceneSave) {
                return;
            }
            //this.getWebsocket().send(JSON.stringify({ type: 'interact', text: "!save" }));
        },

        // characters

        requestCharacterList() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_list',
            }));
        },

        requestCharacter(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_details',
                name: name,
            }));
        },

        loadCharacter(name) {
            this.requestCharacter(name);
            this.selectedCharacterPage = 'description';
            this.selectedCharacter = name;
        },

        // character attributes

        filteredCharacterAttributes() {
            if (this.characterAttributeSearch === null) {
                return this.characterDetails.base_attributes;
            }

            let filtered = {};
            for (let attribute in this.characterDetails.base_attributes) {
                if (attribute.toLowerCase().includes(this.characterAttributeSearch.toLowerCase())) {
                    filtered[attribute] = this.characterDetails.base_attributes[attribute];
                }
            }
            return filtered;
        },

        autoSelectFilteredAttribute() {
            // if there is only one attribute in the filtered list, select it
            if (Object.keys(this.filteredCharacterAttributes()).length === 1) {
                this.selectedCharacterAttribute = Object.keys(this.filteredCharacterAttributes())[0];
            }
        },

        queueUpdateCharacterAttribute(name) {
            if (this.characterAttributeUpdateTimeout !== null) {
                clearTimeout(this.characterAttributeUpdateTimeout);
            }

            this.characterAttributeDirty = true;

            this.characterAttributeUpdateTimeout = setTimeout(() => {
                this.updateCharacterAttribute(name);
            }, 500);
        },

        updateCharacterAttribute(name) {
            return this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_attribute',
                name: this.selectedCharacter,
                attribute: name,
                value: this.characterDetails.base_attributes[name],
            }));
        },

        setAndUpdateCharacterAttribute(name, value) {
            this.characterDetails.base_attributes[name] = value;
            this.updateCharacterAttribute(name);
        },

        handleNewCharacterAttribute() {
            this.characterDetails.base_attributes[this.newCharacterAttributeName] = "";
            this.selectedCharacterAttribute = this.newCharacterAttributeName;
            this.newCharacterAttributeName = null;
            // set focus to the new attribute
            this.$refs.characterAttribute.focus();
        },

        deleteCharacterAttribute(name) {
            // set value to blank
            this.characterDetails.base_attributes[name] = "";
            this.removeCharacterAttributeConfirm = false;
            // send update
            this.updateCharacterAttribute(name);
            // remove attribute from list
            delete this.characterDetails.base_attributes[name];
            this.selectedCharacterAttribute = null;
        },

        // character details

        filteredCharacterDetails() {
            if (this.characterDetailSearch === null) {
                return this.characterDetails.details;
            }

            let filtered = {};
            for (let detail in this.characterDetails.details) {
                if (detail.toLowerCase().includes(this.characterDetailSearch.toLowerCase())) {
                    filtered[detail] = this.characterDetails.details[detail];
                }
            }
            return filtered;
        },

        autoSelectFilteredDetail() {
            // if there is only one detail in the filtered list, select it
            if (Object.keys(this.filteredCharacterDetails()).length === 1) {
                this.selectedCharacterDetail = Object.keys(this.filteredCharacterDetails())[0];
            }
        },

        queueUpdateCharacterDetail(name) {
            if (this.characterDetailUpdateTimeout !== null) {
                clearTimeout(this.characterDetailUpdateTimeout);
            }

            this.characterDetailDirty = true;

            this.characterDetailUpdateTimeout = setTimeout(() => {
                this.updateCharacterDetail(name);
            }, 500);
        },

        updateCharacterDetail(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_detail',
                name: this.selectedCharacter,
                detail: name,
                value: this.characterDetails.details[name],
            }));
        },

        setAndUpdateCharacterDetail(name, value) {
            this.characterDetails.details[name] = value;
            this.updateCharacterDetail(name);
        },

        handleNewCharacterDetail() {
            this.characterDetails.details[this.newCharacterDetailName] = "";
            this.selectedCharacterDetail = this.newCharacterDetailName;
            this.newCharacterDetailName = null;
            // set focus to the new detail
            this.$refs.characterDetail.focus();
        },

        deleteCharacterDetail(name) {
            // set value to blank
            this.characterDetails.details[name] = "";
            this.removeCharacterDetailConfirm = false;
            // send update
            this.updateCharacterDetail(name);
            // remove detail from list
            delete this.characterDetails.details[name];
            this.selectedCharacterDetail = null;
        },

        // Character state reinforcement

        characterStateTemplatesAvailable() {
            for (let template in this.templates.state_reinforcement) {
                if (this.templates.state_reinforcement[template].state_type == "character" || this.templates.state_reinforcement[template].state_type == "npc" || this.templates.state_reinforcement[template].state_type == "player") {
                    return true;
                }
            }
        },

        characterStateTemplates() {
            return Object.values(this.templates.state_reinforcement).filter(template => {
                return template.state_type == "character" || template.state_type == "npc" || template.state_type == "player";
            });
        },

        addCharacterStateFromTemplate(template, characterName) {
            this.characterStateTemplateBusy = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: '!apply_world_state_template:' + template.name + ':state_reinforcement:' + characterName,
            }));
        },

        filteredCharacterStateReinforcers() {
            if (this.characterStateReinforcerSearch === null) {
                return this.characterDetails.reinforcements;
            }

            let filtered = {};
            for (let detail in this.characterDetails.reinforcements) {
                if (detail.toLowerCase().includes(this.characterStateReinforcerSearch.toLowerCase())) {
                    filtered[detail] = this.characterDetails.reinforcements[detail];
                }
            }
            return filtered;
        },

        autoSelectFilteredStateReinforcer() {
            // if there is only one detail in the filtered list, select it
            if (Object.keys(this.filteredCharacterStateReinforcers()).length === 1) {
                this.selectedCharacterStateReinforcer = Object.keys(this.filteredCharacterStateReinforcers())[0];
            }
        },

        viewCharacterStateReinforcer(name) {
            if (this.characterDetails.reinforcements[name]) {
                this.selectedCharacterStateReinforcer = name;
            } else {
                this.addCharacterStateReinforcement(name);
                this.updateCharacterStateReinforcement(name, true);
                this.selectedCharacterStateReinforcer = name;
            }
            this.selectedCharacterPage = 'reinforce';
        },

        handleNewCharacterStateReinforcer() {
            this.addCharacterStateReinforcement(this.newCharacterStateReinforcerQuestion);
            this.updateCharacterStateReinforcement(this.newCharacterStateReinforcerQuestion, true);
            this.selectedCharacterStateReinforcer = this.newCharacterStateReinforcerQuestion;
            this.newCharacterStateReinforcerQuestion = null;
        },

        addCharacterStateReinforcement(name) {
            this.characterDetails.reinforcements[name] = {
                interval: this.characterDetailReinforceInterval,
                instructions: this.characterDetailReinforceIntructions,
                insert: this.newCharacterStateReinforcerInsert,
            };
        },

        queueUpdateCharacterStateReinforcement(name) {
            if (this.characterStateReinforcerUpdateTimeout !== null) {
                clearTimeout(this.characterStateReinforcerUpdateTimeout);
            }

            this.characterStateReinforcerDirty = true;

            this.characterStateReinforcerUpdateTimeout = setTimeout(() => {
                this.updateCharacterStateReinforcement(name);
            }, 500);
        },

        updateCharacterStateReinforcement(name, updateState) {
            let interval = this.characterDetails.reinforcements[name].interval;
            let instructions = this.characterDetails.reinforcements[name].instructions;
            let insert = this.characterDetails.reinforcements[name].insert;
            if (updateState === true)
                this.isBusy = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_character_detail_reinforcement',
                name: this.selectedCharacter,
                question: name,
                interval: interval,
                instructions: instructions,
                answer: this.characterDetails.reinforcements[name].answer,
                update_state: updateState,
                insert: insert,
            }));
        },

        deleteCharacterStateReinforcement(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_character_detail_reinforcement',
                name: this.selectedCharacter,
                question: name,
            }));

            if (this.characterDetails.reinforcements[name])
                delete this.characterDetails.reinforcements[name];

            this.removeCharacterStateReinforcerConfirm = false;

            // select first detail
            if (this.selectedCharacterStateReinforcer == name)
                this.selectedCharacterStateReinforcer = Object.keys(this.characterDetails.reinforcements)[0];
        },

        runCharacterStateReinforcement(name, reset) {
            this.isBusy = true;

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'run_character_detail_reinforcement',
                name: this.selectedCharacter,
                question: name,
                reset: reset || false,
            }));

            this.resetCharacterStateReinforcerConfirm = false;
        },

        // character description

        queueUpdateCharacterDescription() {
            if (this.characterDescriptionUpdateTimeout !== null) {
                clearTimeout(this.characterDescriptionUpdateTimeout);
            }

            this.characterDescriptionDirty = true;

            this.characterDescriptionUpdateTimeout = setTimeout(() => {
                this.updateCharacterDescription();
            }, 500);
        },

        updateCharacterDescription() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_description',
                name: this.selectedCharacter,
                attribute: 'description',
                value: this.characterDetails.description,
            }));
        },

        // contextdb
        isHiddenMetaTag(name) {
            return name === "session"
        },

        visibleMetaTags(meta) {
            let tags = {}
            for (let name in meta) {
                if (!this.isHiddenMetaTag(name)) {
                    tags[name] = meta[name];
                }
            }
            return tags;
        },

        queryContextDB() {
            let meta = {};

            if (!this.contextDBQuery) {
                return;
            }

            if (this.contextDBQueryMetaKey !== null && this.contextDBQueryMetaValue !== null) {
                meta[this.contextDBQueryMetaKey] = this.contextDBQueryMetaValue;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'query_context_db',
                query: this.contextDBQuery || "",
                meta: meta
            }));
        },

        loadContextDBEntry(id) {
            this.contextDBQuery = "id:" + id;
            this.queryContextDB();
            this.tab = 'contextdb';
        },

        handleNewContextDBEntryMeta() {
            if (this.newContextDBEntryMetaKey === null || this.newContextDBEntryMetaValue === null) {
                return;
            }
            this.newContextDBEntryMeta[this.newContextDBEntryMetaKey] = this.newContextDBEntryMetaValue;
            this.newContextDBEntryMetaKey = null;
            this.newContextDBEntryMetaValue = null;
        },

        handleRemoveContextDBEntryMeta(name) {
            delete this.newContextDBEntryMeta[name];
        },

        queueUpdateContextDBEntry(entry) {
            if (this.contextDBEntryUpdateTimeout !== null) {
                clearTimeout(this.contextDBEntryUpdateTimeout);
            }

            entry.dirty = true;

            this.contextDBEntryUpdateTimeout = setTimeout(() => {
                this.updateContextDBEntry(entry);
                entry.dirty = false;
            }, 500);
        },

        updateContextDBEntry(entry) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_context_db',
                id: entry.id,
                text: entry.text,
                meta: entry.meta,
            }));
        },

        addContextDBEntry() {
            let meta = {};
            for (let key in this.newContextDBEntryMeta) {
                meta[key] = this.newContextDBEntryMeta[key];
            }

            meta.source = "manual";

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_context_db',
                text: this.newContextDBEntryText,
                meta: meta,
            }));
            this.newContextDBEntryText = null;
            this.newContextDBEntryMeta = {};
            this.dialogAddContextDBEntry = false;
        },

        deleteContextDBEntry(id) {
            let confirm = window.confirm("Are you sure you want to delete this entry?");
            if (!confirm) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_context_db',
                id: id,
            }));
        },

        resetContextDB() {
            let confirm = window.confirm("Are you sure you want to reset the context database? This will remove all entries and reimport them from the current save file. Manually added context entries will be lost.");
            if (!confirm) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: "!ltm_reset",
            }));
        },

        // pins

        requestPins() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_pins',
            }));
        },

        pinsExist() {
            return Object.keys(this.pins).length > 0;
        },

        entryHasPin(entryId) {
            return this.pins[entryId] !== undefined;
        },

        entryIsPinned(entryId) {
            return this.entryHasPin(entryId) && this.pins[entryId].pin.active;
        },

        selectPin(entryId) {
            this.selectedPin = this.pins[entryId];
            this.tab = 'pins';
        },

        addPin(entryId) {

            this.pins[entryId] = {
                text: "",
                pin: {
                    entry_id: entryId,
                    active: false,
                    condition: "",
                    condition_state: false,
                }
            };
            this.selectPin(entryId);

            this.updatePin(this.pins[entryId]);
        },

        removePin(entryId) {
            delete this.pins[entryId];
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'remove_pin',
                entry_id: entryId,
            }));
            this.selectedPin = null;
            this.removePinConfirm = false;
        },

        updatePin(pin) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_pin',
                entry_id: pin.pin.entry_id,
                active: pin.pin.active,
                condition: pin.pin.condition,
                condition_state: pin.pin.condition_state,
            }));
        },

        queueUpdatePin(pin) {
            if (this.pinUpdateTimeout !== null) {
                clearTimeout(this.pinUpdateTimeout);
            }

            this.pinUpdateTimeout = setTimeout(() => {
                this.updatePin(pin);
            }, 500);
        },

        // websocket

        requestTemplates: function () {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_templates',
            }));
        },

        handleMessage(message) {

            if (message.type === 'status' && message.status === 'success' && message.message === 'Auto state added.') {
                console.log("auto state added", message);
                if (this.selectedCharacter) {
                    if (message.data.reinforcement) {
                        this.characterDetails.reinforcements[message.data.reinforcement.question] = message.data.reinforcement;
                        this.selectedCharacterStateReinforcer = message.data.reinforcement.question;
                    }
                    //this.requestCharacter(this.selectedCharacter); 

                }
                this.characterStateTemplateBusy = false;
                return;
            }

            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action === 'character_list') {
                this.characterList = message.data;
            }
            else if (message.action === 'character_details') {
                this.characterDetails = message.data;
                // select first attribute
                if (!this.selectedCharacterAttribute)
                    this.selectedCharacterAttribute = Object.keys(this.characterDetails.base_attributes)[0];
                // select first detail
                if (!this.selectedCharacterDetail)
                    this.selectedCharacterDetail = Object.keys(this.characterDetails.details)[0];

                // loop through characterDetails.base_attributes and characterDetails.details and convert any objects to strings
                for (let attribute in this.characterDetails.base_attributes) {
                    if (typeof this.characterDetails.base_attributes[attribute] === 'object') {
                        this.characterDetails.base_attributes[attribute] = JSON.stringify(this.characterDetails.base_attributes[attribute]);
                    }
                }
            }
            else if (message.action === 'pins') {
                this.pins = message.data.pins;
                if (this.selectedPin != null)
                    this.selectedPin = this.pins[this.selectedPin.pin.entry_id];
                this.requireSceneSave = true;
            }
            else if (message.action === 'character_attribute_updated') {
                this.characterAttributeDirty = false;
                this.requireSceneSave = true;
            }
            else if (message.action === 'character_detail_updated') {
                this.characterDetailDirty = false;
                this.requireSceneSave = true;
            }
            else if (message.action === 'character_description_updated') {
                this.characterDescriptionDirty = false;
                this.requireSceneSave = true;
            }
            else if (message.action === 'character_detail_reinforcement_set') {
                this.characterStateReinforcerDirty = false;
                this.requireSceneSave = true;
            }
            else if (message.action === 'character_detail_reinforcement_deleted') {
                this.requireSceneSave = true;
            }
            else if (message.action === 'context_db_result') {
                this.contextDB = message.data;
                this.contextDBCurrentQuery = this.contextDBQuery;
            }
            else if (message.action === 'context_db_updated') {
                this.requestPins();
                if (this.selectedCharacter)
                    this.requestCharacter(this.selectedCharacter);
                this.$refs.world.requestWorld();
            }
            else if (message.action === 'context_db_deleted') {
                let entry_id = message.data.id;
                for (let i = 0; i < this.contextDB.entries.length; i++) {
                    if (this.contextDB.entries[i].id === entry_id) {
                        this.contextDB.entries.splice(i, 1);
                        break;
                    }
                }
            }
            else if (message.action == 'templates') {
                this.templates = message.data;
            }
            else if (message.action === 'operation_done') {
                this.isBusy = false;
            }

        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped>.inactive {
    opacity: 0.5;
}

.pre-wrap {
    white-space: pre-wrap;
}</style>
