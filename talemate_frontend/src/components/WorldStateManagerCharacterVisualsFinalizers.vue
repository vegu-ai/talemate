<template>
    <v-alert
        v-if="promptFinalizationOff"
        type="warning"
        variant="text"
        density="compact"
        class="mt-4"
    >
        Prompt Finalization is turned off on the Visualizer agent, so the actions below will not run. Enable it under Agents → Visualizer → Prompt Finalization.
    </v-alert>

    <ConfigWidgetTable
        :key="character?.name"
        class="mt-4"
        :columns="columns"
        :default_values="finalizers"
        :allow_reorder="true"
        :save-target="character?.name"
        description="Post-processing actions applied to image generation prompts involving this character. Actions run in order, after the visualizer agent's own prompt finalization."
        @save="saveFinalizers"
    />

    <v-card variant="outlined" color="muted" class="mt-4">
        <v-card-text>
            <div class="d-flex align-start">
                <v-icon class="mr-3 mt-1" color="primary">mdi-information-outline</v-icon>
                <div class="text-muted">
                    <div class="text-primary text-subtitle-2 font-weight-bold mb-1">About Prompt Finalization</div>
                    <p class="text-body-2 mb-2">
                        Each action rewrites the generated image prompt right before it is sent to the image generation backend, whenever this character is the subject.
                    </p>
                    <p class="text-body-2 mb-0">
                        <strong>Examples:</strong> exact-replace "red hair" with "crimson hair", fuzzy-remove a keyword the model keeps producing, or run an AI instruction over the whole prompt.
                    </p>
                </div>
            </div>
        </v-card-text>
    </v-card>
</template>

<script>
import ConfigWidgetTable from './ConfigWidgetTable.vue';
import { finalizerTableColumns } from '@/constants/visual';

export default {
    name: 'WorldStateManagerCharacterVisualsFinalizers',
    components: {
        ConfigWidgetTable,
    },
    props: {
        character: Object,
        scene: Object,
        agentStatus: Object,
    },
    data() {
        return {
            columns: finalizerTableColumns(),
        }
    },
    inject: ['getWebsocket'],
    computed: {
        finalizers() {
            return this.character?.visual_finalizers || [];
        },
        // only warn on an explicit false — unknown/missing status stays quiet
        promptFinalizationOff() {
            return this.agentStatus?.visual?.meta?.prompt_finalization_enabled === false;
        },
    },
    methods: {
        // characterName is the table's echoed save-target — on a flush from
        // an unmounting table it names the character the rows were edited
        // for, which may no longer be the selected one
        saveFinalizers(rows, characterName) {
            if (!characterName) return;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_visual_finalizers',
                name: characterName,
                visual_finalizers: rows,
            }));
        }
    }
}
</script>
