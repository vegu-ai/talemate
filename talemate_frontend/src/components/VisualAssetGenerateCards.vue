<template>
    <v-row class="mt-2 generate-cards-row" dense>
        <!-- Generate Variation Card -->
        <v-col cols="12" md="6" v-if="showVariation" class="pb-8">
            <v-card class="generate-card" elevation="7">
                <v-card-text>
                    <div class="d-flex align-center mb-2">
                        <v-icon class="mr-2" color="secondary">mdi-image</v-icon>
                        <strong>{{ variationLabel }}</strong>
                    </div>
                    <p class="text-caption text-medium-emphasis mb-0">
                        <slot name="variation-description"></slot>
                    </p>
                    <v-alert
                        v-if="!imageEditAvailable"
                        icon="mdi-alert-circle-outline"
                        density="compact"
                        variant="text"
                        color="warning"
                        class="mt-2 mb-0"
                    >
                        Image editing backend is not configured. Configure an image editing backend in Visual Agent settings to generate variations.
                    </v-alert>
                </v-card-text>
                <v-card-actions>
                    <v-btn
                        @click="$emit('generate-variation')"
                        color="secondary"
                        variant="tonal"
                        prepend-icon="mdi-image"
                        size="small"
                        :disabled="!imageEditAvailable"
                        block
                    >
                        {{ variationLabel }}
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-col>

        <!-- Generate New Card -->
        <v-col cols="12" md="6" class="pb-8">
            <v-card class="generate-card" elevation="7">
                <v-card-text>
                    <div class="d-flex align-center mb-2">
                        <v-icon class="mr-2" color="primary">mdi-image-plus</v-icon>
                        <strong>Generate New</strong>
                    </div>
                    <p class="text-caption text-medium-emphasis mb-0">
                        Create a completely new {{ newLabel }} from scratch using natural language instructions.
                        The visual agent will generate a prompt and create a new image based on your description.
                    </p>
                    <v-alert
                        v-if="!imageCreateAvailable"
                        icon="mdi-alert-circle-outline"
                        density="compact"
                        variant="text"
                        color="warning"
                        class="mt-2 mb-0"
                    >
                        Image creation backend is not configured. Configure a text-to-image backend in Visual Agent settings to generate {{ createWarningSubject }}.
                    </v-alert>
                </v-card-text>
                <v-card-actions>
                    <v-btn
                        @click="$emit('generate-new')"
                        color="primary"
                        variant="tonal"
                        prepend-icon="mdi-image-plus"
                        size="small"
                        :disabled="!imageCreateAvailable"
                        block
                    >
                        Generate New
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-col>
    </v-row>
</template>

<script>
export default {
    name: 'VisualAssetGenerateCards',
    props: {
        showVariation: Boolean,
        variationLabel: {
            type: String,
            default: 'Generate Variation',
        },
        // Noun for the Generate New description, e.g. 'cover image', 'portrait'.
        newLabel: {
            type: String,
            required: true,
        },
        // Noun phrase for the missing-backend warning, e.g. 'new cover images'.
        createWarningSubject: {
            type: String,
            default: 'new images',
        },
        imageEditAvailable: Boolean,
        imageCreateAvailable: Boolean,
    },
    emits: ['generate-variation', 'generate-new'],
}
</script>
