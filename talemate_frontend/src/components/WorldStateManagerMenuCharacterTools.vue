<template>
    <v-list density="compact" slim>
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-account-multiple-plus</v-icon>
            Create
        </v-list-subheader>
        <v-list-item :disabled="newCharacter !== null" prepend-icon="mdi-account-plus" @click.stop="openCharacterCreator(true)">
            <v-list-item-title>Create Character</v-list-item-title>
            <v-list-item-subtitle class="text-caption">Add a new character to the scene.</v-list-item-subtitle>
        </v-list-item>

        <v-list-item prepend-icon="mdi-account-arrow-right" @click.stop="openCharacterImporter">
            <v-list-item-title>Import Character</v-list-item-title>
            <v-list-item-subtitle class="text-caption">Import from another scene.</v-list-item-subtitle>
        </v-list-item>
    </v-list>
    <v-list density="compact" slim selectable color="primary" v-model:selected="selected" :opened="openedFolders" @update:opened="onOpenedChange" open-strategy="multiple">
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-account-group</v-icon>
            Characters
        </v-list-subheader>
        <v-list-item v-if="newCharacter !== null" prepend-icon="mdi-account-outline" class="text-unsaved" @click.stop="openCharacterCreator()" value="$NEW">
            <v-list-item-title class="font-italic">
                {{ newCharacter.name || "New character" }}
            </v-list-item-title>
            <v-list-item-subtitle>
                <div class="text-caption">
                    <v-chip v-if="!newCharacter.is_player" label size="x-small" color="warning" elevation="7">AI</v-chip>
                    <v-chip v-else label size="x-small" color="info" elevation="7">Player</v-chip>
                </div>
            </v-list-item-subtitle>
        </v-list-item>

        <!-- Ungrouped characters -->
        <WorldStateManagerCharacterListItem
            v-for="character in folderedGroups.ungrouped"
            :key="character.name"
            :character="character"
            :selected-name="selectedName"
            :avatar-src="character.avatar ? getAssetSrc(character.avatar) : ''"
            @open="openCharacterEditor"
        />

        <!-- Folders -->
        <v-list-group
            v-for="folder in folderedGroups.folders"
            :key="`folder-${folder.name}`"
            :value="folder.name"
            class="character-folder-group"
        >
            <template v-slot:activator="{ props }">
                <v-list-item v-bind="props">
                    <template v-slot:prepend>
                        <v-chip label size="x-small" variant="flat" :color="folder.anyActive ? 'success' : 'grey-darken-3'" class="mr-2 folder-count-chip">{{ folder.count }}</v-chip>
                    </template>
                    <v-list-item-title>{{ folder.name }}</v-list-item-title>
                    <template v-slot:append>
                        <v-btn
                            size="x-small"
                            variant="text"
                            icon="mdi-pencil"
                            density="comfortable"
                            @click.stop="openRenameDialog(folder.name)"
                        />
                    </template>
                </v-list-item>
            </template>

            <WorldStateManagerCharacterListItem
                v-for="character in folder.members"
                :key="character.name"
                :character="character"
                :selected-name="selectedName"
                :avatar-src="character.avatar ? getAssetSrc(character.avatar) : ''"
                @open="openCharacterEditor"
            />
        </v-list-group>
    </v-list>

    <CharacterImporter ref="characterImporter" @import-done="requestCharacterList" />

    <!-- Rename folder dialog -->
    <v-dialog v-model="renameDialog.open" max-width="400" @keydown.enter="submitRename">
        <v-card>
            <v-card-title>
                <v-icon class="mr-1" color="primary">mdi-folder-edit-outline</v-icon>
                Rename folder
            </v-card-title>
            <v-card-text>
                <v-text-field
                    ref="renameInput"
                    v-model="renameDialog.newName"
                    label="Folder name"
                    :error-messages="renameDialog.error ? [renameDialog.error] : []"
                    autofocus
                    density="compact"
                    :maxlength="folderNameMaxLength"
                />
                <p class="text-caption text-muted">
                    Renaming "<span class="text-primary">{{ renameDialog.oldName }}</span>" will update every character currently assigned to it.
                </p>
            </v-card-text>
            <v-card-actions>
                <v-spacer />
                <v-btn variant="text" @click="renameDialog.open = false">Cancel</v-btn>
                <v-btn color="primary" variant="tonal" prepend-icon="mdi-check" @click="submitRename">Rename</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>

import CharacterImporter from './CharacterImporter.vue';
import WorldStateManagerCharacterListItem from './WorldStateManagerCharacterListItem.vue';
import VisualAssetsMixin from './VisualAssetsMixin.js';
import { FOLDER_NAME_MAX_LENGTH } from '@/constants/character';

export default {
    name: "WorldStateManagerMenuCharacterTools",
    mixins: [VisualAssetsMixin],
    components: {
        CharacterImporter,
        WorldStateManagerCharacterListItem,
    },
    props: {
        scene: Object,
        character: Object,
        title: String,
        icon: String,
        manager: Object,
    },
    watch:{
        selected: {
            immediate: true,
            handler(selected) {
                let characterName = selected ? selected[0] : null;
                if(characterName === "$NEW") {
                    return;
                }

                this.$emit('world-state-manager-navigate', 'characters', characterName, 'description');
            }
        },
        'scene.data.id': {
            immediate: true,
            handler() {
                this.loadExpandedFolders();
            },
        },
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
            newCharacter: null,
            expandedFolders: new Set(),
            renameDialog: {
                open: false,
                oldName: '',
                newName: '',
                error: '',
            },
        }
    },
    computed: {
        folderNameMaxLength() {
            return FOLDER_NAME_MAX_LENGTH;
        },
        selectedName() {
            return this.selected && this.selected[0] !== '$NEW' ? this.selected[0] : null;
        },
        folderedGroups() {
            const ungrouped = [];
            const folders = {};
            const characters = this.characterList && this.characterList.characters
                ? Object.values(this.characterList.characters)
                : [];
            for (const character of characters) {
                if (character.folder) {
                    (folders[character.folder] ??= []).push(character);
                } else {
                    ungrouped.push(character);
                }
            }
            return {
                ungrouped,
                folders: Object.entries(folders)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([name, members]) => ({
                        name,
                        members,
                        count: members.length,
                        anyActive: members.some((m) => m.active),
                    })),
            };
        },
        expandedStorageKey() {
            const sceneId = this.scene && this.scene.data ? this.scene.data.id : null;
            return `wsm.characterFolders.expanded.${sceneId || 'unknown'}`;
        },
        openedFolders() {
            return [...this.expandedFolders];
        },
    },
    emits: [
        'world-state-manager-navigate'
    ],
    methods: {
        onSelect(value) {
            this.selected = value && value.length ? value[0] : null;
        },
        requestCharacterList() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_list',
            }));
        },
        openCharacterEditor(character) {
            this.manager.selectCharacter(character.name);
        },
        loadAvatars() {
            const avatarIds = Object.values(this.characterList.characters)
                .map(character => character.avatar)
                .filter(Boolean);
            this.loadAssets(avatarIds);
        },
        openCharacterCreator(reset) {
            if(!this.newCharacter || reset) {
                this.newCharacter = {
                    is_new: true,
                    is_player: false,
                    name: '',
                    description: '',
                    attributes: [],
                    details: [],
                    reinforcements: [],
                    actor: null,
                    shared: false,

                    generation_context: {
                        enabled: true,
                        instructions: "",
                        generateAttributes: true,
                    },
                    cancel: () => {
                        this.newCharacter = null;
                    },
                    created: () => {
                        this.newCharacter = null;
                        this.requestCharacterList();
                    }
                }
            }
            this.$nextTick(() => {
                this.manager.newCharacter(this.newCharacter);
                this.selected = ["$NEW"];
            });
        },
        openCharacterImporter() {
            this.$refs.characterImporter.show();
        },
        hasSceneId() {
            return !!(this.scene && this.scene.data && this.scene.data.id);
        },
        loadExpandedFolders() {
            if (!this.hasSceneId()) {
                // Scene id not yet available — start from a clean slate rather
                // than loading from an 'unknown' bucket that could hold leaked
                // state from an earlier session.
                this.expandedFolders = new Set();
                return;
            }
            try {
                const raw = localStorage.getItem(this.expandedStorageKey);
                this.expandedFolders = new Set(raw ? JSON.parse(raw) : []);
            } catch {
                this.expandedFolders = new Set();
            }
        },
        persistExpandedFolders() {
            if (!this.hasSceneId()) {
                return;
            }
            try {
                localStorage.setItem(
                    this.expandedStorageKey,
                    JSON.stringify([...this.expandedFolders]),
                );
            } catch {
                // localStorage might be disabled / full; collapsed state is disposable
            }
        },
        pruneExpandedFolders(existingFolderNames) {
            // Drop any persisted folder names that no longer exist (e.g., the
            // last member was moved out, or the folder was renamed). Keeps the
            // localStorage bucket from accumulating stale entries forever.
            let changed = false;
            const next = new Set();
            for (const name of this.expandedFolders) {
                if (existingFolderNames.has(name)) {
                    next.add(name);
                } else {
                    changed = true;
                }
            }
            if (changed) {
                this.expandedFolders = next;
                this.persistExpandedFolders();
            }
        },
        onOpenedChange(opened) {
            // Vuetify emits the full array of currently-open group identifiers.
            this.expandedFolders = new Set(opened || []);
            this.persistExpandedFolders();
        },
        openRenameDialog(folderName) {
            this.renameDialog = {
                open: true,
                oldName: folderName,
                newName: folderName,
                error: '',
            };
        },
        submitRename() {
            const trimmed = (this.renameDialog.newName || '').trim();
            if (!trimmed) {
                this.renameDialog.error = 'Folder name cannot be empty.';
                return;
            }
            if (trimmed.length > FOLDER_NAME_MAX_LENGTH) {
                this.renameDialog.error = `Folder name is too long (max ${FOLDER_NAME_MAX_LENGTH} characters).`;
                return;
            }
            if (trimmed === this.renameDialog.oldName) {
                this.renameDialog.open = false;
                return;
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'rename_character_folder',
                old_name: this.renameDialog.oldName,
                new_name: trimmed,
            }));
            // Carry expanded state across the rename so the folder stays open.
            if (this.expandedFolders.has(this.renameDialog.oldName)) {
                const next = new Set(this.expandedFolders);
                next.delete(this.renameDialog.oldName);
                next.add(trimmed);
                this.expandedFolders = next;
                this.persistExpandedFolders();
            }
            this.renameDialog.open = false;
        },
        handleMessage(message) {
            // Handle scene_asset messages using mixin method
            this.handleSceneAssetMessage(message);

            // Handle avatar changes - refresh character list to show updated avatars
            if (message.type === 'scene_asset_character_avatar') {
                if (message.asset_id) {
                    this.loadAssets([message.asset_id]);
                }
                // Refresh character list to show updated avatar
                this.requestCharacterList();
                return;
            }

            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action === 'character_list') {
                // Before replacing the list, diff per-character folder membership
                // so we can auto-expand destination folders for any character
                // that just moved into a folder.
                const previousMembership = new Map();
                const previousCharacters = this.characterList && this.characterList.characters
                    ? Object.values(this.characterList.characters)
                    : [];
                for (const c of previousCharacters) {
                    previousMembership.set(c.name, c.folder || null);
                }

                this.characterList = message.data;

                const newCharacters = message.data && message.data.characters
                    ? Object.values(message.data.characters)
                    : [];
                const existingFolders = new Set();
                const foldersToExpand = new Set();
                for (const c of newCharacters) {
                    if (c.folder) {
                        existingFolders.add(c.folder);
                    }
                    const previous = previousMembership.has(c.name)
                        ? previousMembership.get(c.name)
                        : null;
                    const current = c.folder || null;
                    if (current && current !== previous) {
                        foldersToExpand.add(current);
                    }
                }
                // Drop any stale folder names from our persisted expanded set.
                this.pruneExpandedFolders(existingFolders);
                // Then apply any auto-expansions from the diff.
                if (foldersToExpand.size > 0) {
                    const next = new Set(this.expandedFolders);
                    foldersToExpand.forEach((f) => next.add(f));
                    this.expandedFolders = next;
                    this.persistExpandedFolders();
                }

                this.$nextTick(() => {
                    this.loadAvatars();
                });
            } else if(message.action === 'character_deleted') {
                if(this.selected === message.data.name) {
                    this.selected = null;
                }
            }
        }
    },
    mounted() {
        this.requestCharacterList();
        this.loadAvatars();
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    }
}

</script>

<style scoped>
/* Reduce the default indent Vuetify applies to v-list-group children — the
   sidebar is narrow and the full indent wastes horizontal space. */
.character-folder-group :deep(.v-list-group__items .v-list-item) {
    padding-inline-start: 24px !important;
}
</style>
