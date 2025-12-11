<template>
    <v-row>
        <v-col cols="3">
            <v-tabs color="secondary" direction="vertical" v-model="tab">
                <v-tab value="cover" class="text-caption" prepend-icon="mdi-image-frame">
                    Cover Image
                </v-tab>
                <v-tab value="avatar" class="text-caption" prepend-icon="mdi-account-circle">
                    Avatar
                </v-tab>
            </v-tabs>
        </v-col>
        <v-col cols="9">
            <WorldStateManagerCharacterVisualsCover 
                v-if="tab === 'cover'"
                ref="cover"
                :character="character"
                :scene="scene"
                :visual-agent-ready="visualAgentReady"
                :image-edit-available="imageEditAvailable"
                :image-create-available="imageCreateAvailable"
                @require-scene-save="$emit('require-scene-save')"
            />
            <WorldStateManagerCharacterVisualsAvatar 
                v-else-if="tab === 'avatar'"
                ref="avatar"
                :character="character"
                :scene="scene"
                :visual-agent-ready="visualAgentReady"
                :image-edit-available="imageEditAvailable"
                :image-create-available="imageCreateAvailable"
                @require-scene-save="$emit('require-scene-save')"
            />
        </v-col>
    </v-row>
</template>

<script>
import WorldStateManagerCharacterVisualsCover from './WorldStateManagerCharacterVisualsCover.vue';
import WorldStateManagerCharacterVisualsAvatar from './WorldStateManagerCharacterVisualsAvatar.vue';

export default {
    name: 'WorldStateManagerCharacterVisuals',
    components: {
        WorldStateManagerCharacterVisualsCover,
        WorldStateManagerCharacterVisualsAvatar,
    },
    data() {
        return {
            tab: 'cover',
        }
    },
    props: {
        character: Object,
        scene: Object,
        visualAgentReady: Boolean,
        imageEditAvailable: Boolean,
        imageCreateAvailable: Boolean,
    },
    emits: [
        'require-scene-save',
    ],
}
</script>
