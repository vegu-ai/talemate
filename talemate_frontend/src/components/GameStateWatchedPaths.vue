<template>
    <v-card>
        <v-card-title class="text-subtitle-1">Pinned Variables</v-card-title>
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
                <span class="text-caption text-medium-emphasis mr-1">Pin to</span>
                <v-chip-group v-model="selectedTargets" multiple filter>
                    <v-chip value="debug" size="small" color="primary" variant="outlined">
                        <v-icon start>mdi-bug-outline</v-icon>
                        Debug Vars
                    </v-chip>
                    <v-chip value="knob" size="small" color="primary" variant="outlined">
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
                        <th class="text-center target-column">Debug Vars</th>
                        <th class="text-center target-column">Scene toolbar</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="path in managedPaths" :key="path">
                        <td class="text-caption pin-path" :title="path">{{ path }}</td>
                        <td>
                            <v-text-field
                                :model-value="pathLabels[path] || ''"
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
                                :model-value="knobPaths.includes(path)"
                                @update:model-value="setTarget(path, 'knob', $event)"
                                density="compact"
                                color="primary"
                                :aria-label="`Show ${path} in the scene toolbar`"
                            />
                        </td>
                    </tr>
                </tbody>
            </v-table>

            <v-alert v-else color="muted" density="compact" variant="text" class="mt-2">
                No pinned paths. Add a path to Debug Vars, the scene toolbar, or both.
            </v-alert>
        </v-card-text>
    </v-card>
</template>

<script>
export default {
    name: 'GameStateWatchedPaths',
    props: {
        watchedPaths: {
            type: Array,
            default: () => [],
        },
        knobPaths: {
            type: Array,
            default: () => [],
        },
        pathLabels: {
            type: Object,
            default: () => ({}),
        },
        availablePaths: {
            type: Array,
            default: () => [],
        },
    },
    emits: ['set-target', 'set-label', 'debug-path-added'],
    data() {
        return {
            selectedPath: null,
            selectedLabel: '',
            selectedTargets: ['debug'],
        };
    },
    computed: {
        managedPaths() {
            return [...new Set([...this.watchedPaths, ...this.knobPaths])].sort();
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
                ...(label ? { label } : {}),
            });
            if (this.selectedTargets.includes('debug')) {
                this.$emit('set-target', targetChange('debug'));
                if (!this.watchedPaths.includes(path)) {
                    this.$emit('debug-path-added', path);
                }
            }
            if (this.selectedTargets.includes('knob')) {
                this.$emit('set-target', targetChange('knob'));
            }
            this.selectedPath = null;
            this.selectedLabel = '';
        },
        setTarget(path, target, enabled) {
            this.$emit('set-target', { path, target, enabled });
        },
        setLabel(path, value) {
            const label = (value || '').trim();
            if (label === (this.pathLabels[path] || '')) return;
            this.$emit('set-label', { path, label: label || null });
        },
    },
};
</script>

<style scoped>
.pin-target-table :deep(table) {
    table-layout: fixed;
}

.path-column {
    width: 34%;
}

.label-column {
    width: 30%;
}

.target-column {
    width: 18%;
    white-space: normal;
}

.pin-path {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
</style>
