<template>
    <v-card>
        <v-card-title class="text-body-large">Pinned Variables</v-card-title>
        <v-card-text>
            <v-autocomplete
                v-model="selectedPath"
                :items="availablePaths"
                label="Add game state path"
                density="compact"
                variant="outlined"
                hide-details
            />

            <v-text-field
                v-model="selectedLabel"
                label="Optional label"
                placeholder="Uses the path when blank"
                density="compact"
                variant="outlined"
                hide-details
                class="mt-2"
            />

            <div class="d-flex flex-wrap align-center mt-2" style="gap: 6px;">
                <span class="text-body-small text-medium-emphasis mr-1">Pin to</span>
                <v-chip-group v-model="selectedTargets" multiple filter>
                    <v-chip value="debug" size="small" color="primary" variant="outlined">
                        <v-icon start>mdi-bug-outline</v-icon>
                        Debug Vars
                    </v-chip>
                    <v-chip value="control" size="small" color="primary" variant="outlined">
                        <v-icon start>mdi-tune-variant</v-icon>
                        Scene toolbar
                    </v-chip>
                </v-chip-group>
                <v-spacer />
                <v-btn
                    prepend-icon="mdi-plus"
                    size="small"
                    variant="text"
                    color="primary"
                    :disabled="!selectedPath || selectedTargets.length === 0"
                    @click="addPath"
                >
                    Add
                </v-btn>
            </div>

            <v-table density="compact" v-if="managedPaths.length > 0" class="mt-2 pin-target-table">
                <thead>
                    <tr>
                        <th class="text-left path-column">Path</th>
                        <th class="text-left label-column">Label</th>
                        <th class="text-center target-column">Debug</th>
                        <th class="text-center target-column">Scene</th>
                        <th class="text-center settings-column"></th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="path in managedPaths" :key="path">
                        <td class="text-body-small pin-path" :title="path">{{ path }}</td>
                        <td>
                            <v-text-field
                                :model-value="pathSettings[path]?.label || ''"
                                @blur="setLabel(path, $event.target.value)"
                                placeholder="Optional"
                                density="compact"
                                variant="underlined"
                                hide-details
                                :aria-label="`Label for ${path}`"
                            />
                        </td>
                        <td class="text-center">
                            <v-checkbox-btn
                                :model-value="watchedPaths.includes(path)"
                                @update:model-value="setTarget(path, 'debug', $event)"
                                density="compact"
                                color="primary"
                                :aria-label="`Show ${path} in Debug Vars`"
                            />
                        </td>
                        <td class="text-center">
                            <v-checkbox-btn
                                :model-value="controlPaths.includes(path)"
                                @update:model-value="setTarget(path, 'control', $event)"
                                density="compact"
                                color="primary"
                                :aria-label="`Show ${path} in the scene toolbar`"
                            />
                        </td>
                        <td class="text-center">
                            <v-btn
                                icon="mdi-tune"
                                size="small"
                                variant="text"
                                color="primary"
                                :aria-label="`Control settings for ${path}`"
                                @click="openSettings(path)"
                            />
                        </td>
                    </tr>
                </tbody>
            </v-table>

            <v-alert v-else color="muted" density="compact" variant="text" class="mt-2">
                No pinned paths. Add a path to Debug Vars, the scene toolbar, or both.
            </v-alert>

            <GameStatePathSettingsDialog
                v-model="settingsDialog"
                :path="settingsPath"
                :settings="pathSettings[settingsPath] || {}"
                :value="settingsValue"
                @save="$emit('set-settings', $event)"
            />
        </v-card-text>
    </v-card>
</template>

<script>
import GameStatePathSettingsDialog from './GameStatePathSettingsDialog.vue';
import { getGameStateValue } from '@/utils/gameStatePaths.js';

export default {
    name: 'GameStateWatchedPaths',
    components: {
        GameStatePathSettingsDialog,
    },
    props: {
        watchedPaths: {
            type: Array,
            default: () => [],
        },
        controlPaths: {
            type: Array,
            default: () => [],
        },
        pathSettings: {
            type: Object,
            default: () => ({}),
        },
        variables: {
            type: Object,
            default: () => ({}),
        },
        availablePaths: {
            type: Array,
            default: () => [],
        },
    },
    emits: ['set-target', 'set-settings', 'debug-path-added'],
    data() {
        return {
            selectedPath: null,
            selectedLabel: '',
            selectedTargets: ['debug'],
            settingsDialog: false,
            settingsPath: '',
        };
    },
    computed: {
        managedPaths() {
            return [...new Set([...this.watchedPaths, ...this.controlPaths])].sort();
        },
        settingsValue() {
            return getGameStateValue(this.variables, this.settingsPath);
        },
    },
    methods: {
        addPath() {
            if (!this.selectedPath || this.selectedTargets.length === 0) return;

            const path = this.selectedPath;
            const label = this.selectedLabel.trim();
            const targetChange = (target) => ({
                path,
                target,
                enabled: true,
                ...(label ? { settings: { label } } : {}),
            });
            if (this.selectedTargets.includes('debug')) {
                this.$emit('set-target', targetChange('debug'));
                if (!this.watchedPaths.includes(path)) {
                    this.$emit('debug-path-added', path);
                }
            }
            if (this.selectedTargets.includes('control')) {
                this.$emit('set-target', targetChange('control'));
            }
            this.selectedPath = null;
            this.selectedLabel = '';
        },
        setTarget(path, target, enabled) {
            this.$emit('set-target', { path, target, enabled });
        },
        setLabel(path, value) {
            const label = (value || '').trim();
            const settings = this.pathSettings[path] || {};
            if (label === (settings.label || '')) return;
            this.$emit('set-settings', {
                path,
                settings: { ...settings, label: label || null },
            });
        },
        openSettings(path) {
            this.settingsPath = path;
            this.settingsDialog = true;
        },
    },
};
</script>

<style scoped>
.pin-target-table :deep(table) {
    table-layout: fixed;
}

.path-column {
    width: 28%;
}

.label-column {
    width: 26%;
}

.target-column {
    width: 18%;
    white-space: nowrap;
}

.settings-column {
    width: 10%;
}

.pin-path {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
</style>
