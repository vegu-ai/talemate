<template>
    <v-card flat>
        <v-card-text>
            <v-toolbar floating density="compact" class="mb-2" color="grey-darken-4">
                <v-text-field v-model="query" label="Content search"
                    append-inner-icon="mdi-magnify" clearable single-line hide-details density="compact"
                    variant="underlined" class="ml-1 mb-1 mr-1"
                    @keyup.enter="requestQuery"></v-text-field>

                <v-select v-model="queryMetaKey" :items="metaKeys" label="Filter By Tag"
                    class="mr-1 mb-1" variant="underlined" single-line hide-details
                    density="compact"></v-select>
                <v-select
                    v-if="queryMetaKey !== null && metaValuesByType[queryMetaKey]"
                    v-model="queryMetaValue"
                    :items="metaValuesByType[queryMetaKey]()" label="Tag value"
                    class="mr-1 mb-1" variant="underlined" single-line hide-details
                    density="compact"></v-select>
                <v-text-field v-else v-model="queryMetaValue" label="Tag value" class="mr-1 mb-1"
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
                        <v-list-item @click.stop="resetDB" append-icon="mdi-shield-alert">
                            <v-list-item-title>Reset</v-list-item-title>
                        </v-list-item>
                    </v-list>
                </v-menu>

                <!-- button to open add content db entry dialog -->
                <v-btn rounded="sm" prepend-icon="mdi-plus" @click.stop="dialogAddEntry = true"
                    variant="text">
                    Add entry
                </v-btn>
            </v-toolbar>
            <v-divider></v-divider>
            <!-- add entry-->
            <v-card v-if="dialogAddEntry === true">
                <v-card-title>
                    Add entry
                </v-card-title>
                <v-card-text>
                    <v-row>
                        <v-col cols="12">
                            <v-textarea rows="5" auto-grow v-model="newEntry.text" label="Content"
                                hint="The content of the entry."></v-textarea>
                        </v-col>
                    </v-row>
                    <v-row>
                        <v-col cols="12">
                            <v-chip v-for="(value, name) in newEntry.meta" :key="name" label
                                size="x-small" variant="outlined" class="ml-1" closable
                                @click:close="handleRemove(name)">{{ name }}: {{ value
                                }}</v-chip>
                        </v-col>
                    </v-row>
                    <v-row>
                        <v-col cols="3">
                            <v-select v-model="newEntry.metaKey" :items="metaKeys"
                                label="Meta key" class="mr-1 mb-1" variant="underlined" single-line
                                hide-details density="compact"></v-select>
                        </v-col>
                        <v-col cols="3">
                            <v-select
                                v-if="newEntry.metaKey !== null && metaValuesByType[newEntry.metaKey]"
                                v-model="newEntry.metaValue"
                                :items="metaValuesByType[newEntry.metaKey]()"
                                label="Meta value" class="mr-1 mb-1" variant="underlined" single-line
                                hide-details density="compact"></v-select>
                            <v-text-field v-else v-model="newEntry.metaValue" label="Meta value"
                                class="mr-1 mb-1" variant="underlined" single-line hide-details
                                density="compact"></v-text-field>
                        </v-col>
                        <v-col cols="3">
                            <v-btn rounded="sm" color="primary" prepend-icon="mdi-plus"
                                @click.stop="handleNew" variant="text">
                                Add meta
                            </v-btn>
                        </v-col>
                    </v-row>
                </v-card-text>
                <v-card-actions>
                    <!-- cancel -->
                    <v-btn rounded="sm" prepend-icon="mdi-cancel"
                        @click.stop="dialogAddEntry = false" color="info" variant="text">
                        Cancel
                    </v-btn>
                    <v-spacer></v-spacer>
                    <!-- add -->
                    <v-btn rounded="sm" prepend-icon="mdi-plus" @click.stop="add"
                        color="primary" variant="text">
                        Add
                    </v-btn>
                </v-card-actions>
            </v-card>

            <!-- results -->
            <div v-else>
                <v-table v-if="contextDB.entries.length > 0">
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
                                            @click.stop="remove(entry.id)">
                                            <v-icon>mdi-close-box-outline</v-icon>
                                        </v-btn>
                                    </template>
                                </v-tooltip>
                            </td>
                            <td>
                                <v-textarea rows="1" auto-grow density="compact" hide-details
                                    :color="entry.dirty ? 'dirty' : ''" v-model="entry.text"
                                    @update:model-value="queueUodate(entry)"
                                    >
                                </v-textarea>
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
                <v-alert v-else-if="currentQuery" dense type="warning" variant="text"
                    icon="mdi-information-outline">
                    No results
                </v-alert>
                <v-alert v-else dense color="muted" variant="text" icon="mdi-magnify">
                    Enter a query to search the context database.
                </v-alert>
            </div>

        </v-card-text>
    </v-card>
</template>

<script>

export default {
    name: "WorldStateManagerContextDB",
    components: {

    },
    props: {
        characterList: Object,
        pins: Object,
    },
    data() {
        return {
            updateTimeout: null,
            query: null,
            queryMetaKey: null,
            queryMetaValue: null,
            currentQuery: null,
            contextDB: { entries: [] },
            metaKeys: [
                "character",
                "typ",
                "ts",
                "detail",
                "item",
            ],
            metaValuesByType: {
                character: () => {
                    let list = Object.keys(this.characterList.characters);
                    list.push("__narrator__");
                    return list;
                },
                typ: () => {
                    return ["base_attribute", "details", "history", "world_state", "lore"]
                },
            },
            selected: null,
            dialogAddEntry: false,
            newEntry: {
                text: null,
                metaKey: null,
                metaValue: null,
                meta: {},
            },
        }
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
    ],
    emits:[
        'require-scene-save',
        'load-pin',
        'add-pin',
        'request-sync',
    ],
    methods: {
        reset() {
            this.query = null;
            this.queryMetaKey = null;
            this.queryMetaValue = null;
            this.currentQuery = null;
            this.contextDB = { entries: [] };
        },

        entryHasPin(entryId) {
            return this.pins[entryId] !== undefined;
        },

        selectPin(entryId) {
            this.$emit('load-pin', entryId);
        },

        addPin(entryId) {
            this.$emit('add-pin', entryId)
        },

        entryIsPinned(entryId) {
            return this.entryHasPin(entryId) && this.pins[entryId].pin.active;
        },

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

        requestQuery() {
            let meta = {};

            if (!this.query) {
                return;
            }

            if (this.queryMetaKey !== null && this.queryMetaValue !== null) {
                meta[this.queryMetaKey] = this.queryMetaValue;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'query_context_db',
                query: this.query || "",
                meta: meta
            }));
        },

        load(id) {
            this.query = "id:" + id;
            this.requestQuery();
            this.tab = 'contextdb';
        },

        handleNew() {
            if (this.newEntry.metaKey === null || this.newEntry.metaValue === null) {
                return;
            }
            this.newEntry.meta[this.newEntry.metaKey] = this.newEntry.metaValue;
            this.newEntry.metaKey = null;
            this.newEntry.metaValue = null;
        },

        handleRemove(name) {
            delete this.newEntry.meta[name];
        },

        queueUodate(entry, delay = 1500) {
            if (this.updateTimeout !== null) {
                clearTimeout(this.updateTimeout);
            }

            entry.dirty = true;

            this.updateTimeout = setTimeout(() => {
                this.update(entry);
                entry.dirty = false;
            }, delay);
        },

        update(entry) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_context_db',
                id: entry.id,
                text: entry.text,
                meta: entry.meta,
            }));
        },

        add() {
            let meta = {};
            for (let key in this.newEntry.meta) {
                meta[key] = this.newEntry.meta[key];
            }

            meta.source = "manual";

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_context_db',
                text: this.newEntry.text,
                meta: meta,
            }));
            this.newEntry.text = null;
            this.newEntry.meta = {};
            this.dialogAddEntry = false;
        },

        remove(id) {
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

        resetDB() {
            let confirm = window.confirm("Are you sure you want to reset the context database? This will remove all entries and reimport them from the current save file. Manually added context entries will be lost.");
            if (!confirm) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: "!ltm_reset",
            }));
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            else if (message.action === 'context_db_result') {
                this.contextDB = message.data;
                this.currentQuery = this.contextDBQuery;
            }
            else if (message.action === 'context_db_updated') {
                this.$emit('request-sync')
                //this.load(message.data.id);
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

        }
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    }
}

</script>