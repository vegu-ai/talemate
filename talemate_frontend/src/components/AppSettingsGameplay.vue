<template>
    <v-row>
        <v-col cols="12" data-setting-anchor="auto_save">
            <v-checkbox color="primary" v-model="config.game.general.auto_save" label="Auto save" messages="Automatically save after each game-loop"></v-checkbox>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols="12" data-setting-anchor="auto_progress">
            <v-checkbox color="primary" v-model="config.game.general.auto_progress" label="Auto progress" messages="AI automatically progresses after player turn."></v-checkbox>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols="6" data-setting-anchor="max_backscroll">
            <v-number-input v-model="config.game.general.max_backscroll" label="Max backscroll" messages="Maximum number of messages to keep in the scene backscroll"></v-number-input>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols="12" data-setting-anchor="show_agent_activity_bar">
            <v-checkbox color="primary" v-model="config.game.general.show_agent_activity_bar" label="Show agent activity bar" messages="Display active agent actions in a horizontal bar above scene controls"></v-checkbox>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols="12" data-setting-anchor="scene_header">
            <v-checkbox color="primary" v-model="config.game.scene_header.enabled" label="Show scene header" messages="Keep the scene title and your chosen information items at the top of the scene. The header's own close button turns this off as well, and the item menus on each side of the header pick the items."></v-checkbox>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols="6" data-setting-anchor="scene_header_slot_a">
            <v-select v-model="config.game.scene_header.slot_a" :items="headerItems" :item-props="headerItemProps" label="Left of the title" multiple chips closable-chips messages="Information items shown left of the scene title."></v-select>
        </v-col>
        <v-col cols="6" data-setting-anchor="scene_header_slot_b">
            <v-select v-model="config.game.scene_header.slot_b" :items="headerItems" :item-props="headerItemProps" label="Right of the title" multiple chips closable-chips messages="Information items shown right of the scene title."></v-select>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols="12" data-setting-anchor="release_gpu_cache_on_scene_load">
            <v-checkbox color="primary" v-model="config.game.general.release_gpu_cache_on_scene_load" label="Release GPU cache on scene load" messages="Hand idle GPU memory reserved by local CUDA embeddings/TTS back to the driver when switching scenes, so it doesn't pile up and eventually leave too little VRAM to load another scene. Disable only if you have VRAM to spare and would rather keep it reserved."></v-checkbox>
        </v-col>
    </v-row>
</template>

<script>
import { SCENE_HEADER_ITEMS } from '@/utils/sceneHeaderItems.js';

export default {
    name: 'AppSettingsGameplay',
    props: {
        config: Object,
    },
    data() {
        return {
            headerItems: SCENE_HEADER_ITEMS,
        };
    },
    methods: {
        headerItemProps(item) {
            return { title: item.label, subtitle: item.description, value: item.id };
        },
    },
}
</script>
