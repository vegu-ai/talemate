<template>
    <v-form class="mt-4">
        <v-row>
            <v-col cols="12" lg="6">
                <v-text-field
                    v-model="scene.title"
                    label="Title"
                    :placeholder="scene.name"
                ></v-text-field>
            </v-col>
        </v-row>
        <v-row>
            <v-col cols="12" lg="3">
                <v-combobox
                    v-model="scene.context"
                    :items="appConfig ? appConfig.creator.content_context: []"
                    messages="This can strongly influence the type of content that is generated, during narration, dialogue and world building generation."
                    label="Content context"
                ></v-combobox>
            </v-col>
        </v-row>
    </v-form>
</template>

<script>

export default {
    name: "WorldStateManagerSceneOutline",
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