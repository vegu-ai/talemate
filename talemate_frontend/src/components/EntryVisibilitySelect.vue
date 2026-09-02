<template>
    <div class="d-flex align-center flex-wrap">
        <v-select
            :model-value="mode"
            :items="modes"
            item-title="label"
            item-value="value"
            label="Known by"
            density="compact"
            variant="underlined"
            hide-details
            style="max-width: 220px"
            :disabled="disabled"
            @update:model-value="setMode">
            <template v-slot:prepend-inner>
                <v-icon size="small" :icon="modeIcon"></v-icon>
            </template>
        </v-select>
        <v-combobox
            v-if="mode === 'list'"
            :model-value="characters"
            :items="characterNames"
            label="Characters"
            density="compact"
            variant="underlined"
            hide-details
            multiple
            chips
            closable-chips
            class="ml-3"
            style="min-width: 240px"
            :disabled="disabled"
            @update:model-value="setCharacters"></v-combobox>
        <v-tooltip activator="parent" location="top">{{ hint }}</v-tooltip>
    </div>
</template>

<script>
export default {
    name: 'EntryVisibilitySelect',
    props: {
        modelValue: Object,
        characterNames: {
            type: Array,
            default: () => [],
        },
        ownerLabel: {
            type: String,
            default: 'the owner',
        },
        disabled: Boolean,
    },
    emits: ['update:modelValue'],
    computed: {
        mode() {
            return this.modelValue?.mode || 'everyone';
        },
        characters() {
            return this.modelValue?.characters || [];
        },
        modes() {
            return [
                { label: 'Everyone', value: 'everyone' },
                { label: `Only ${this.ownerLabel}`, value: 'owner' },
                { label: 'Specific characters', value: 'list' },
            ];
        },
        modeIcon() {
            return {
                everyone: 'mdi-earth',
                owner: 'mdi-lock',
                list: 'mdi-account-multiple',
            }[this.mode];
        },
        hint() {
            return {
                everyone: 'Every character can draw on this entry.',
                owner: `Only ${this.ownerLabel} knows this entry, unless a knowledge grant names another character.`,
                list: 'Only the listed characters (and the owner) know this entry, unless a knowledge grant names another character.',
            }[this.mode];
        },
    },
    methods: {
        setMode(mode) {
            this.$emit('update:modelValue', { mode, characters: mode === 'list' ? this.characters : [] });
        },
        setCharacters(characters) {
            this.$emit('update:modelValue', { mode: 'list', characters });
        },
    },
}
</script>
