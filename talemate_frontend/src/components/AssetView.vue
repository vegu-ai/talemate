<template>
    <v-dialog v-model="showDialog" width="auto" @update:model-value="onDialogUpdate">
        <v-card>
            <v-card-title class="d-flex justify-space-between align-center">
                <span>Asset View</span>
                <v-btn icon variant="text" @click="close">
                    <v-icon>mdi-close</v-icon>
                </v-btn>
            </v-card-title>
            <v-divider></v-divider>
            <v-card-text>
                <v-img
                    v-if="imageSrc"
                    :src="imageSrc"
                    contain
                    :width="previewWidth"
                    ref="previewImage"
                    @load="onImageLoad"
                />
            </v-card-text>
        </v-card>
    </v-dialog>
</template>

<script>
export default {
    name: 'AssetView',
    props: {
        modelValue: {
            type: Boolean,
            default: false,
        },
        imageSrc: {
            type: String,
            default: null,
        },
    },
    emits: ['update:modelValue'],
    data() {
        return {
            imageWidth: null,
            imageHeight: null,
        };
    },
    computed: {
        showDialog: {
            get() {
                return this.modelValue;
            },
            set(value) {
                this.$emit('update:modelValue', value);
            },
        },
        previewWidth() {
            // vertical
            const isVertical = this.imageWidth && this.imageHeight && this.imageWidth < this.imageHeight;
            const isSquare = this.imageWidth && this.imageHeight && this.imageWidth === this.imageHeight;
            if (isVertical) {
                return '800px';
            } else if (isSquare) {
                return '1280px';
            }
            return '1600px';
        },
    },
    methods: {
        close() {
            this.showDialog = false;
        },
        onDialogUpdate(value) {
            if (value && this.imageSrc) {
                // Reset dimensions when dialog opens
                this.imageWidth = null;
                this.imageHeight = null;
            }
        },
        onImageLoad() {
            if (this.$refs.previewImage && this.$refs.previewImage.$el) {
                const img = this.$refs.previewImage.$el.querySelector('img');
                if (img) {
                    this.imageWidth = img.naturalWidth;
                    this.imageHeight = img.naturalHeight;
                }
            }
        },
    },
};
</script>

<style scoped>
/* Styles can be added here if needed */
</style>

