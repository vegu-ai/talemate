<template>
    <v-tabs color="secondary" v-model="tab" :disabled="busy">
        <v-tab v-for="t in tabs" :key="t.value" :value="t.value">
            <v-icon start>{{ t.icon }}</v-icon>
            {{ t.title }}
        </v-tab>
    </v-tabs>
    <v-window v-model="tab">
        <v-window-item value="scene">
            <AppConfigAppearanceScene ref="scene" :immutableConfig="immutableConfig" :sceneActive="sceneActive"></AppConfigAppearanceScene>
        </v-window-item>
    </v-window>
</template>

<script>

import AppConfigAppearanceScene from './AppConfigAppearanceScene.vue';

export default {
    name: 'AppConfigAppearance',
    components: {
        AppConfigAppearanceScene,
    },
    props: {
        immutableConfig: Object,
        sceneActive: Boolean,
    },
    emits: [
    ],
    data() {
        return {
            tab: 'scene',
            tabs: [
                { title: 'Scene', icon: 'mdi-script-text', value: 'scene' },
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
            return config;
        }
    },
}

</script>