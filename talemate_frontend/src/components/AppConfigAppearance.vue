<template>
    <v-tabs color="secondary" v-model="tab">
        <v-tab v-for="t in tabs" :key="t.value" :value="t.value">
            <v-icon start>{{ t.icon }}</v-icon>
            {{ t.title }}
        </v-tab>
    </v-tabs>
    <v-window v-model="tab">
        <v-window-item value="scene">
            <AppConfigAppearanceScene ref="scene" :immutableConfig="immutableConfig" :sceneActive="sceneActive" @changed="onChildChanged"></AppConfigAppearanceScene>
        </v-window-item>
        <v-window-item value="assets">
            <AppConfigAppearanceAssets ref="assets" :immutableConfig="immutableConfig" :sceneActive="sceneActive" @changed="onChildChanged"></AppConfigAppearanceAssets>
        </v-window-item>
    </v-window>
</template>

<script>

import AppConfigAppearanceScene from './AppConfigAppearanceScene.vue';
import AppConfigAppearanceAssets from './AppConfigAppearanceAssets.vue';

export default {
    name: 'AppConfigAppearance',
    components: {
        AppConfigAppearanceScene,
        AppConfigAppearanceAssets,
    },
    props: {
        immutableConfig: Object,
        sceneActive: Boolean,
    },
    emits: [
        'appearance-preview',
    ],
    data() {
        return {
            tab: 'scene',
            tabs: [
                { title: 'Messages', icon: 'mdi-script-text', value: 'scene' },
                { title: 'Visuals', icon: 'mdi-image-outline', value: 'assets' },
            ]
        }
    },
    methods: {
        get_config() {
            let config = {
                scene: this.immutableConfig.appearance.scene,
            };
            if(this.$refs.scene) {
                config.scene = this.$refs.scene.config;
            }
            // Merge message_assets config from Assets component
            if(this.$refs.assets && this.$refs.assets.get_config) {
                const assetsConfig = this.$refs.assets.get_config();
                if(assetsConfig) {
                    if(!config.scene) {
                        config.scene = {};
                    }
                    config.scene.message_assets = assetsConfig;
                }
            }
            // Include auto_attach_assets from Assets component
            if(this.$refs.assets && this.$refs.assets.get_auto_attach_assets) {
                if(!config.scene) {
                    config.scene = {};
                }
                config.scene.auto_attach_assets = this.$refs.assets.get_auto_attach_assets();
            }
            return config;
        },
        onChildChanged() {
            // When any child component changes, emit preview with merged config
            const previewConfig = this.get_config();
            this.$emit('appearance-preview', previewConfig);
        },
    },
}

</script>