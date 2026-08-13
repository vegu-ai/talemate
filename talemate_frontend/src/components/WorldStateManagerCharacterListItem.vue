<template>
    <v-list-item :value="character.name" @click.stop="$emit('open', character)">
        <template v-slot:prepend>
            <div v-if="avatarSrc" class="character-avatar-square mr-2">
                <v-img :src="avatarSrc" cover />
            </div>
            <v-icon v-else>mdi-account</v-icon>
        </template>
        <v-list-item-title>{{ character.name }}</v-list-item-title>
        <v-list-item-subtitle>
            <div class="text-caption">
                <v-chip v-if="character.is_player === true" label size="x-small"
                    :variant="selectedName === character.name ? 'flat' : 'tonal'" color="info">Player</v-chip>
                <v-chip v-else-if="character.is_player === false" label size="x-small"
                    :variant="selectedName === character.name ? 'flat' : 'tonal'" color="warning">AI</v-chip>
                <v-chip v-if="character.active === true"
                    label size="x-small" :variant="selectedName === character.name ? 'flat' : 'tonal'" color="success"
                    class="ml-1">Active</v-chip>
                <v-icon v-if="character.shared === true" color="highlight6" class="ml-1">mdi-earth</v-icon>
            </div>
        </v-list-item-subtitle>
    </v-list-item>
</template>

<script>
export default {
    name: 'WorldStateManagerCharacterListItem',
    props: {
        character: { type: Object, required: true },
        selectedName: { type: String, default: null },
        avatarSrc: { type: String, default: '' },
    },
    emits: ['open'],
}
</script>

<style scoped>
.character-avatar-square {
    width: 40px;
    height: 40px;
    border-radius: 0;
    overflow: hidden;
    flex-shrink: 0;
}
</style>
