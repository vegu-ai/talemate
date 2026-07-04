<template>
    <div class="ma-3">
        <v-alert color="white" variant="text" icon="mdi-image-outline" density="compact" class="mb-3">
            <v-alert-title>Message Visual Rendering</v-alert-title>
            <div class="text-grey">
                Control when visuals are rendered inline with scene messages.
            </div>
        </v-alert>
        <v-divider class="mb-3"></v-divider>
        
        <v-row class="mb-3">
            <v-col cols="12">
                <v-checkbox 
                    color="primary" 
                    v-model="autoAttachAssets" 
                    label="Auto-attach visuals" 
                    messages="Automatically attach visuals when possible"
                    hide-details="auto"
                ></v-checkbox>
            </v-col>
        </v-row>
        
        <v-divider class="mb-3"></v-divider>
        
        <v-table density="compact">
            <thead>
                <tr>
                    <th class="text-left" style="padding: 8px 12px;">Visual Type</th>
                    <th class="text-left" style="padding: 8px 12px;">Render Cadence</th>
                    <th class="text-left" style="padding: 8px 12px;">Display Size</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td style="padding: 4px 12px;">
                        <div class="d-flex align-center">
                            <v-icon class="mr-2">mdi-account-circle</v-icon>
                            <div class="text-caption font-weight-medium">Portrait</div>
                        </div>
                    </td>
                    <td style="padding: 4px 12px;">
                        <v-select
                            v-model="config.avatar.cadence"
                            :items="cadenceOptions"
                            density="compact"
                            variant="outlined"
                            hide-details
                            style="max-width: 200px;"
                        ></v-select>
                    </td>
                    <td style="padding: 4px 12px;">
                        <v-select
                            v-model="config.avatar.size"
                            :items="sizeOptions"
                            density="compact"
                            variant="outlined"
                            hide-details
                            style="max-width: 200px;"
                        ></v-select>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 4px 12px;">
                        <div class="d-flex align-center">
                            <v-icon class="mr-2">mdi-card-account-details</v-icon>
                            <div class="text-caption font-weight-medium">Card</div>
                        </div>
                    </td>
                    <td style="padding: 4px 12px;">
                        <v-select
                            v-model="config.card.cadence"
                            :items="cadenceOptionsNoChange"
                            density="compact"
                            variant="outlined"
                            hide-details
                            style="max-width: 200px;"
                        ></v-select>
                    </td>
                    <td style="padding: 4px 12px;">
                        <v-select
                            v-model="config.card.size"
                            :items="sizeOptions"
                            density="compact"
                            variant="outlined"
                            hide-details
                            style="max-width: 200px;"
                        ></v-select>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 4px 12px;">
                        <div class="d-flex align-center">
                            <v-icon class="mr-2">mdi-image-area</v-icon>
                            <div class="text-caption font-weight-medium">Scene Illustration</div>
                        </div>
                    </td>
                    <td style="padding: 4px 12px;">
                        <v-select
                            v-model="config.scene_illustration.cadence"
                            :items="cadenceOptionsNoChange"
                            density="compact"
                            variant="outlined"
                            hide-details
                            style="max-width: 200px;"
                        ></v-select>
                    </td>
                    <td style="padding: 4px 12px;">
                        <v-select
                            v-model="config.scene_illustration.size"
                            :items="sceneIllustrationSizeOptions"
                            density="compact"
                            variant="outlined"
                            hide-details
                            style="max-width: 200px;"
                        ></v-select>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 4px 12px;">
                        <div class="d-flex align-center">
                            <v-icon class="mr-2">mdi-image-filter-hdr</v-icon>
                            <div class="text-caption font-weight-medium">Scene Background</div>
                        </div>
                    </td>
                    <td style="padding: 4px 12px;">
                        <v-select
                            v-model="config.scene_background.cadence"
                            :items="cadenceOptionsNoChange"
                            density="compact"
                            variant="outlined"
                            hide-details
                            style="max-width: 200px;"
                        ></v-select>
                    </td>
                    <td style="padding: 4px 12px;">
                        <v-select
                            v-model="config.scene_background.size"
                            :items="sceneIllustrationSizeOptions"
                            density="compact"
                            variant="outlined"
                            hide-details
                            style="max-width: 200px;"
                        ></v-select>
                    </td>
                </tr>
            </tbody>
        </v-table>

        <v-row v-for="kind in backgroundConfiguredKinds" :key="kind" class="mt-3">
            <v-col cols="12" md="6">
                <v-slider
                    v-model="config[kind].background_panel_opacity"
                    :label="`Message panel opacity (${kindLabels[kind]})`"
                    color="primary"
                    :min="0"
                    :max="1"
                    :step="0.05"
                    thumb-label
                    density="compact"
                    hide-details
                ></v-slider>
            </v-col>
            <v-col cols="12" md="6">
                <v-checkbox
                    v-model="config[kind].background_text_shadow"
                    :label="`Message text shadow (${kindLabels[kind]})`"
                    color="primary"
                    density="compact"
                    hide-details
                ></v-checkbox>
            </v-col>
        </v-row>

        <v-card color="muted" variant="text" class="mt-3">
            <v-card-text class="text-muted">
                <div class="text-caption">
                    <strong>Always:</strong> Show visual on every message<br>
                    <strong>Never:</strong> Never show visual inline with messages<br>
                    <strong>On change:</strong> Only show when visual changes (portraits: tracked per character)<br><br>
                    <strong>Scene Illustration</strong> covers images of the current moment ("Visualize Moment"), <strong>Scene Background</strong> covers purely environmental images ("Visualize Scene (Background)").<br>
                    <strong>Sizes:</strong> Big = full width above message, Small/Medium = inline with text, Background = fills behind the scene text. When both types use Background, the most recent image is the active backdrop.
                </div>
            </v-card-text>
        </v-card>
    </div>
</template>

<script>
import { BACKDROP_ASSET_KINDS } from '@/constants/visual';

function defaultAssetConfig() {
    return {
        avatar: {
            cadence: 'always',
            size: 'medium',
        },
        card: {
            cadence: 'always',
            size: 'medium',
        },
        scene_illustration: {
            cadence: 'always',
            size: 'medium',
            background_panel_opacity: 0.8,
            background_text_shadow: true,
        },
        scene_background: {
            cadence: 'always',
            size: 'medium',
            background_panel_opacity: 0.8,
            background_text_shadow: true,
        },
    };
}

export default {
    name: 'AppConfigAppearanceAssets',
    props: {
        immutableConfig: Object,
        sceneActive: Boolean,
    },
    emits: ['changed'],
    data() {
        return {
            autoAttachAssets: true,
            config: defaultAssetConfig(),
            kindLabels: {
                scene_illustration: 'Scene Illustration',
                scene_background: 'Scene Background',
            },
            cadenceOptions: [
                { title: 'Always', value: 'always' },
                { title: 'Never', value: 'never' },
                { title: 'On change', value: 'on_change' },
            ],
            cadenceOptionsNoChange: [
                { title: 'Always', value: 'always' },
                { title: 'Never', value: 'never' },
            ],
            sizeOptions: [
                { title: 'Small', value: 'small' },
                { title: 'Medium', value: 'medium' },
                { title: 'Big', value: 'big' },
            ],
            isHydrating: false, // Flag to suppress changed events during initialization
        }
    },
    computed: {
        // "background" only makes sense for scene illustrations/backgrounds
        sceneIllustrationSizeOptions() {
            return [...this.sizeOptions, { title: 'Background', value: 'background' }];
        },
        // kinds currently set to the Background display size — each gets its
        // own panel-opacity / text-shadow controls
        backgroundConfiguredKinds() {
            return BACKDROP_ASSET_KINDS.filter(
                kind => this.config[kind].size === 'background'
            );
        },
    },
    watch: {
        immutableConfig: {
            handler: function(newVal) {
                // Suppress changed events during hydration
                this.isHydrating = true;
                
                if (!newVal) {
                    this.config = defaultAssetConfig();
                    this.isHydrating = false;
                    return;
                }

                const sceneConfig = newVal.appearance?.scene || {};
                const messageAssets = sceneConfig.message_assets || {};
                
                // Load auto_attach_assets setting
                this.autoAttachAssets = sceneConfig.auto_attach_assets !== undefined ? sceneConfig.auto_attach_assets : true;
                
                // Overlay stored values onto the defaults (?? so 0 / false
                // survive)
                const config = defaultAssetConfig();
                for (const [kind, entry] of Object.entries(config)) {
                    for (const field of Object.keys(entry)) {
                        entry[field] = messageAssets[kind]?.[field] ?? entry[field];
                    }
                }
                this.config = config;
                
                // Re-enable changed events after hydration completes
                this.$nextTick(() => {
                    this.isHydrating = false;
                });
            },
            immediate: true,
            deep: true,
        },
        config: {
            handler: function(newVal, oldVal) {
                // Emit changed event when config changes (for live preview)
                // Skip initial emit (when oldVal is undefined) and during hydration
                if (oldVal !== undefined && !this.isHydrating) {
                    this.$emit('changed');
                }
            },
            deep: true,
        },
        autoAttachAssets: {
            handler: function(newVal, oldVal) {
                // Emit changed event when autoAttachAssets changes
                if (oldVal !== undefined && !this.isHydrating) {
                    this.$emit('changed');
                }
            },
        },
    },
    methods: {
        // Expose config for parent component
        get_config() {
            return this.config;
        },
        // Expose auto_attach_assets for parent component
        get_auto_attach_assets() {
            return this.autoAttachAssets;
        },
    },
}
</script>
