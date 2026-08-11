<template>
    <v-list-item
        v-for="row in rows"
        :key="row.key"
        density="compact"
        :prepend-icon="row.shortcut.icon"
        :class="{ 'shortcut-not-runnable': !canRun(row) }"
        :disabled="disabled"
        :ripple="canRun(row)"
        @click="(ev) => { runShortcut(ev, row) }"
    >
        <v-list-item-title>{{ rowTitle(row) }} <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">{{ primaryModifierLabel }}: Edit</v-chip></v-list-item-title>
        <v-list-item-subtitle v-if="rowBlockedReason(row)">{{ rowBlockedReason(row) }}</v-list-item-subtitle>
    </v-list-item>

    <v-divider></v-divider>

    <v-list-item
        density="compact"
        prepend-icon="mdi-plus"
        :disabled="disabled"
        @click="$emit('add', section)"
    >
        <v-list-item-title class="text-muted">Add shortcut</v-list-item-title>
    </v-list-item>
</template>

<script>
import { isPrimaryModifier, primaryModifierLabel } from '@/utils/keyboardModifiers';
import { expandShortcutEntries } from '@/utils/sceneToolShortcuts';

export default {
    name: 'SceneToolsShortcutItems',
    props: {
        section: String,
        catalog: {
            type: Array,
            default: () => [],
        },
        shortcuts: {
            type: Object,
            default: () => ({}),
        },
        characters: {
            type: Array,
            default: () => [],
        },
        disabled: Boolean,
        disabledActions: {
            type: Object,
            default: () => ({}),
        },
    },
    emits: ['run', 'edit', 'add'],
    data() {
        return {
            primaryModifierLabel,
        }
    },
    computed: {
        rows() {
            return expandShortcutEntries(this.shortcuts, this.catalog, this.section, this.characters);
        },
    },
    methods: {
        rowTitle(row) {
            return row.character ? `${row.shortcut.label} (${row.character})` : row.shortcut.label;
        },

        canRun(row) {
            return !row.unavailable && !(row.entry.id in this.disabledActions);
        },

        rowBlockedReason(row) {
            if (row.unavailable) {
                return 'No characters to target';
            }
            return this.disabledActions[row.entry.id] || null;
        },

        runShortcut(ev, row) {
            if (isPrimaryModifier(ev)) {
                this.$emit('edit', row.shortcut);
                return;
            }
            if (!this.canRun(row)) {
                return;
            }
            this.$emit('run', {
                shortcut: row.shortcut,
                entry: row.entry,
                character: row.character,
            });
        },
    },
}
</script>

<style scoped>
.shortcut-not-runnable :deep(.v-list-item-title),
.shortcut-not-runnable :deep(.v-list-item__prepend) {
    opacity: 0.5;
}
</style>
