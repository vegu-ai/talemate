<template>
    <v-textarea
        v-model="visualRules"
        label="Static Visual Rules"
        hint="Describe permanent physical traits or anatomical rules that never change"
        rows="10"
        auto-grow
        variant="outlined"
        @blur="saveVisualRules"
        :loading="isSaving"
        persistent-hint
        class="mt-4"
    ></v-textarea>

    <v-card variant="outlined" color="muted" class="mt-4">
        <v-card-text>
            <div class="d-flex align-start">
                <v-icon class="mr-3 mt-1" color="primary">mdi-information-outline</v-icon>
                <div class="text-muted">
                    <div class="text-primary text-subtitle-2 font-weight-bold mb-1">About Static Visual Rules</div>
                    <p class="text-body-2 mb-2">
                        These rules define permanent physical traits that are enforced for <strong>every</strong> image generated for this character.
                    </p>
                    <p class="text-body-2 mb-2">
                        <v-icon size="x-small" color="warning" class="mr-1">mdi-alert-circle-outline</v-icon>
                        <strong>Important:</strong> Do NOT include clothing details, art styles, or anything that might change between scenes.
                    </p>
                    <p class="text-body-2 mb-0">
                        <strong>Examples:</strong> "Always has a cybernetic left arm", "Has a distinct birthmark on their neck", "Has heterochromia (left eye blue, right eye green)"
                    </p>
                </div>
            </div>
        </v-card-text>
    </v-card>
</template>

<script>
export default {
    name: 'WorldStateManagerCharacterVisualsRules',
    props: {
        character: Object,
        scene: Object,
    },
    data() {
        return {
            visualRules: this.character?.visual_rules || '',
            isSaving: false,
        }
    },
    inject: ['getWebsocket'],
    watch: {
        'character.visual_rules': {
            handler(newVal) {
                if (newVal !== this.visualRules) {
                    this.visualRules = newVal || '';
                }
            },
            immediate: true,
        },
    },
    methods: {
        saveVisualRules() {
            if (this.visualRules === this.character?.visual_rules) return;
            
            this.isSaving = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_visual_rules',
                name: this.character.name,
                visual_rules: this.visualRules,
            }));
            
            // We don't necessarily need to wait for a response to stop loading if we trust the WS
            // but the parent will update the prop when the change is broadcasted.
            setTimeout(() => {
                this.isSaving = false;
            }, 500);
        }
    }
}
</script>
