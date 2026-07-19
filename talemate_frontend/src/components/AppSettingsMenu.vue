<template>
    <v-text-field
        v-model="search"
        density="compact"
        variant="solo-filled"
        flat
        hide-details
        clearable
        placeholder="Search settings"
        prepend-inner-icon="mdi-magnify"
        class="ma-2"
    ></v-text-field>

    <!-- search results -->
    <v-list v-if="searchActive" density="compact" slim color="primary" selectable>
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-magnify</v-icon>
            Results
        </v-list-subheader>
        <v-list-item v-if="searchResults.length === 0">
            <v-list-item-subtitle class="text-caption">No settings match "{{ search }}"</v-list-item-subtitle>
        </v-list-item>
        <v-list-item v-for="(result, index) in searchResults" :key="index"
            :active="false"
            @click="onSelectResult(result)">
            <template v-slot:prepend>
                <v-icon>{{ result.page.icon }}</v-icon>
            </template>
            <v-list-item-title>{{ result.entry ? result.entry.label : result.page.title }}</v-list-item-title>
            <v-list-item-subtitle class="text-caption">{{ result.page.group }} · {{ result.page.title }}</v-list-item-subtitle>
        </v-list-item>
    </v-list>

    <!-- navigation -->
    <v-list v-else density="compact" slim color="primary" :selected="[page]" selectable @update:selected="onSelectPage">
        <template v-for="group in groups" :key="group.title">
            <v-list-subheader color="grey">
                <v-icon color="primary" class="mr-1">{{ group.icon }}</v-icon>
                {{ group.title }}
            </v-list-subheader>
            <v-list-item v-for="groupPage in group.pages" :key="groupPage.id" :value="groupPage.id" :prepend-icon="groupPage.icon">
                <v-list-item-title>{{ groupPage.title }}</v-list-item-title>
            </v-list-item>
        </template>
    </v-list>
</template>

<script>
import { SETTINGS_GROUPS, searchSettings } from '../utils/appSettingsRegistry.js';

export default {
    name: 'AppSettingsMenu',
    props: {
        page: String,
    },
    emits: [
        'navigate',
    ],
    data() {
        return {
            groups: SETTINGS_GROUPS,
            search: '',
        }
    },
    computed: {
        searchActive() {
            return (this.search || '').trim() !== '';
        },
        searchResults() {
            return searchSettings(this.search);
        },
    },
    methods: {
        onSelectPage(selection) {
            if (selection.length === 0) {
                return;
            }
            this.$emit('navigate', { page: selection[0], anchor: null });
        },
        onSelectResult(result) {
            this.$emit('navigate', { page: result.page.id, anchor: result.entry ? result.entry.anchor : null });
        },
    },
}
</script>
