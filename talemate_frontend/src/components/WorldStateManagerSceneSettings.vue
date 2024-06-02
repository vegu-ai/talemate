<template>
    <v-form class="mt-4">
        <v-row>
            <v-col cols="12" lg="6">
                <v-checkbox v-model="scene.immutable_save" label="Locked save file" messages="When activated, progress such as conversation and narration cannot be saved to the current file and requires a `Save As` action."></v-checkbox>
                <v-checkbox v-model="scene.experimental" label="Experimental" messages="When activated, the scene will be tagged as experimental. This can be used to indicate whether a scene has components that could potentially make it unstable if used with weaker LLMs."></v-checkbox>
            </v-col>
        </v-row>
    </v-form>
</template>

<script>

export default {
    name: "WorldStateManagerSceneSettings",
    props: {
        immutableScene: Object,
        appConfig: Object,
    },
    watch: {
        immutableScene: {
            immediate: true,
            handler(value) {
                if(value && this.scene && value.name !== this.scene.name) {
                    this.scene = null;
                    this.selected = null;
                }
                if (!value) {
                    this.selected = null;
                    this.scene = null;
                } else {
                    this.scene = { ...value };
                }
            }
        },
    },
    data() {
        return {
            scene: null,
            contentContext: [],
        }
    },
}

</script>