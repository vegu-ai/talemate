<template>
    <v-row>
        <v-col cols="6">
            <v-text-field v-model="config.game.default_player_character.name"
                label="Name"></v-text-field>
        </v-col>
        <v-col cols="6">
            <v-text-field v-model="config.game.default_player_character.gender"
                label="Gender"></v-text-field>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols="12">
            <v-textarea v-model="config.game.default_player_character.description"
                auto-grow label="Description"></v-textarea>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols="12" data-setting-anchor="add_default_character">
            <v-checkbox color="primary" v-model="config.game.general.add_default_character" label="Add default character to blank talemate scenes" messages="When creating a new scene, add the default player character to the scene."></v-checkbox>
        </v-col>
    </v-row>
</template>

<script>
export default {
    name: 'AppSettingsPlayerCharacter',
    props: {
        config: Object,
    },
}
</script>
