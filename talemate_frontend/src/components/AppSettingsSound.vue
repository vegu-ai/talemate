<template>
    <v-row>
        <v-col cols="6" data-setting-anchor="sound_volume">
            <v-slider
                v-model="config.sound.volume"
                label="Sound volume"
                color="primary"
                :min="0"
                :max="1"
                :step="0.01"
                thumb-label
                messages="Playback volume for generated speech and sounds"
            >
                <template v-slot:thumb-label="{ modelValue }">
                    {{ Math.round(modelValue * 100) }}%
                </template>
            </v-slider>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols="12" data-setting-anchor="sound_muted">
            <v-checkbox color="primary" v-model="config.sound.muted" label="Mute sound" messages="Silence all audio playback"></v-checkbox>
        </v-col>
    </v-row>
</template>

<script>
export default {
    name: 'AppSettingsSound',
    props: {
        config: Object,
    },
}
</script>
