<template>
    <v-row>
        <v-col cols="3">
            <v-tabs color="secondary" direction="vertical" v-model="tab">
                <v-tab value="background" class="text-caption" prepend-icon="mdi-image-area">
                    Background Illustration
                </v-tab>
                <v-tab value="illustration" class="text-caption" prepend-icon="mdi-image-filter-hdr">
                    Scene Illustration
                </v-tab>
                <v-tab value="card" class="text-caption" prepend-icon="mdi-image-frame">
                    Scene Card
                </v-tab>
                <v-tab value="finalizers" class="text-caption" prepend-icon="mdi-auto-fix">
                    Prompt Finalization
                </v-tab>
            </v-tabs>
        </v-col>
        <v-col cols="9">
            <WorldStateManagerSceneVisualsAssets
                v-if="tab === 'background'"
                ref="background"
                :vis-type="VIS_TYPE.SCENE_BACKGROUND"
                :scene="scene"
                :visual-agent-ready="visualAgentReady"
                :image-edit-available="imageEditAvailable"
                :image-create-available="imageCreateAvailable"
            />
            <WorldStateManagerSceneVisualsAssets
                v-else-if="tab === 'illustration'"
                ref="illustration"
                :vis-type="VIS_TYPE.SCENE_ILLUSTRATION"
                :scene="scene"
                :visual-agent-ready="visualAgentReady"
                :image-edit-available="imageEditAvailable"
                :image-create-available="imageCreateAvailable"
            />
            <WorldStateManagerSceneVisualsAssets
                v-else-if="tab === 'card'"
                ref="card"
                :vis-type="VIS_TYPE.SCENE_CARD"
                :scene="scene"
                :visual-agent-ready="visualAgentReady"
                :image-edit-available="imageEditAvailable"
                :image-create-available="imageCreateAvailable"
            />
            <WorldStateManagerSceneVisualsFinalizers
                v-else-if="tab === 'finalizers'"
                ref="finalizers"
                :scene="scene"
                :agent-status="agentStatus"
                :app-config="appConfig"
                :templates="templates"
            />
        </v-col>
    </v-row>
</template>

<script>
import WorldStateManagerSceneVisualsAssets from './WorldStateManagerSceneVisualsAssets.vue';
import WorldStateManagerSceneVisualsFinalizers from './WorldStateManagerSceneVisualsFinalizers.vue';
import { VIS_TYPE } from '@/constants/visual';

export default {
    name: 'WorldStateManagerSceneVisuals',
    components: {
        WorldStateManagerSceneVisualsAssets,
        WorldStateManagerSceneVisualsFinalizers,
    },
    data() {
        return {
            tab: 'background',
            VIS_TYPE,
        }
    },
    props: {
        scene: Object,
        appConfig: Object,
        templates: Object,
        agentStatus: Object,
        visualAgentReady: Boolean,
        imageEditAvailable: Boolean,
        imageCreateAvailable: Boolean,
    },
}
</script>
