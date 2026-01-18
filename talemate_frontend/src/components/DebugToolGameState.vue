<template>
    <div>
        <v-card variant="text">
            <v-card-text style="overflow: visible;">
                <div class="d-flex justify-end mb-2">
                    <v-btn size="small" @click="openGameStateEditor" prepend-icon="mdi-code-block-braces" color="primary" variant="text">Edit Game State</v-btn>
                </div>
                
                <v-alert v-if="watchedPaths.length === 0" color="muted" density="compact" variant="text">
                    No watched paths. Add paths to watch in the Game State editor.
                </v-alert>
                
                <div v-else class="d-flex flex-column" style="gap: 10px; overflow: visible;">
                    <div v-for="path in displayPaths" :key="path" style="overflow: visible;">
                        <template v-if="getValueAtPath(path) === undefined">
                            <div class="text-caption mb-1">
                                <v-icon size="small" class="mr-1" color="primary">mdi-variable</v-icon>
                                {{ path }}
                            </div>
                            <div class="text-caption text-error">Path not found in game state</div>
                        </template>

                        <template v-else-if="typeof getValueAtPath(path) === 'string' || typeof getValueAtPath(path) === 'number' || typeof getValueAtPath(path) === 'boolean'">
                            <!-- Editable fields: path is the label -->
                            <v-text-field
                                v-if="typeof getValueAtPath(path) === 'string'"
                                :model-value="draftFor(path, getValueAtPath(path))"
                                @update:model-value="setDraft(path, $event)"
                                @blur="commitDraft(path)"
                                :label="path"
                                density="compact"
                                variant="outlined"
                                hide-details
                                color="primary"
                                style="overflow: visible;"
                            />

                            <v-number-input
                                v-else-if="typeof getValueAtPath(path) === 'number'"
                                :model-value="draftFor(path, getValueAtPath(path))"
                                @update:model-value="setDraft(path, $event)"
                                @blur="commitDraft(path)"
                                :label="path"
                                density="compact"
                                variant="outlined"
                                hide-details
                                control-variant="hidden"
                                color="primary"
                                style="overflow: visible;"
                            />

                            <v-checkbox
                                v-else-if="typeof getValueAtPath(path) === 'boolean'"
                                :model-value="getValueAtPath(path)"
                                @update:model-value="updateValueAtPath(path, $event)"
                                :label="path"
                                density="compact"
                                hide-details
                                color="primary"
                            />
                        </template>

                        <template v-else>
                            <!-- Read-only fields: keep path as a compact header -->
                            <div class="text-caption mb-1">
                                <v-icon size="small" class="mr-1" color="primary">mdi-variable</v-icon>
                                {{ path }}
                            </div>

                            <div v-if="Array.isArray(getValueAtPath(path))" class="text-caption text-grey">
                                List with {{ getValueAtPath(path).length }} items (read-only)
                            </div>

                            <div v-else-if="typeof getValueAtPath(path) === 'object' && getValueAtPath(path) !== null" class="text-caption text-grey">
                                Object with {{ Object.keys(getValueAtPath(path)).length }} keys (read-only)
                            </div>

                            <div v-else class="text-caption text-grey">
                                {{ typeof getValueAtPath(path) }} (read-only)
                            </div>
                        </template>
                    </div>
                </div>
            </v-card-text>
        </v-card>
    </div>
</template>

<script>
export default {
    name: 'DebugToolGameState',
    inject: [
        'getWebsocket',
        'openWorldStateManager',
    ],
    props: {
        scene: {
            type: Object,
            default: () => ({}),
        },
    },
    data() {
        return {
            draftValues: {},
        }
    },
    computed: {
        watchedPaths() {
            return this.scene?.data?.game_state_watch_paths || [];
        },
        gameStateVariables() {
            return this.scene?.data?.game_state?.variables || {};
        },
        displayPaths() {
            const out = [];
            const seen = new Set();

            for (const path of (this.watchedPaths || [])) {
                if (!path) continue;

                const value = this.getValueAtPath(path);

                // If a watched path is a dict/object, expand to top-level keys as separate watched items.
                // This is display-only logic: the persisted watch list remains unchanged.
                if (this.isPlainObject(value)) {
                    const keys = Object.keys(value);

                    // Keep empty objects visible
                    if (keys.length === 0) {
                        if (!seen.has(path)) {
                            seen.add(path);
                            out.push(path);
                        }
                        continue;
                    }

                    keys.sort().forEach((key) => {
                        const expandedPath = `${path}/${key}`;
                        if (!seen.has(expandedPath)) {
                            seen.add(expandedPath);
                            out.push(expandedPath);
                        }
                    });
                    continue;
                }

                if (!seen.has(path)) {
                    seen.add(path);
                    out.push(path);
                }
            }

            return out;
        },
    },
    methods: {
        isPlainObject(value) {
            return value !== null && typeof value === 'object' && !Array.isArray(value);
        },
        draftFor(path, fallbackValue) {
            return Object.prototype.hasOwnProperty.call(this.draftValues, path)
                ? this.draftValues[path]
                : fallbackValue;
        },
        setDraft(path, value) {
            this.draftValues = {
                ...this.draftValues,
                [path]: value,
            };
        },
        commitDraft(path) {
            if (!Object.prototype.hasOwnProperty.call(this.draftValues, path)) {
                return;
            }

            const current = this.getValueAtPath(path);
            let next = this.draftValues[path];

            // Preserve numeric types (in case any component emits strings)
            if (typeof current === 'number' && typeof next === 'string') {
                const trimmed = next.trim();
                next = trimmed === '' ? null : Number(trimmed);
            }

            // Avoid sending updates if unchanged
            if (next === current) {
                const { [path]: _omit, ...rest } = this.draftValues;
                this.draftValues = rest;
                return;
            }

            this.updateValueAtPath(path, next);

            const { [path]: _omit, ...rest } = this.draftValues;
            this.draftValues = rest;
        },
        getValueAtPath(path) {
            if (!path) return undefined;
            const parts = path.split('/');
            let value = this.gameStateVariables;
            
            for (const part of parts) {
                if (value === null || value === undefined || typeof value !== 'object') {
                    return undefined;
                }
                value = value[part];
            }
            
            return value;
        },
        updateValueAtPath(path, newValue) {
            // Clone the variables object
            const updatedVariables = JSON.parse(JSON.stringify(this.gameStateVariables));
            
            // Navigate to the path and update the value
            const parts = path.split('/');
            let current = updatedVariables;
            
            for (let i = 0; i < parts.length - 1; i++) {
                const part = parts[i];
                if (current[part] === undefined || current[part] === null) {
                    current[part] = {};
                }
                current = current[part];
            }
            
            // Set the final value
            const lastPart = parts[parts.length - 1];
            current[lastPart] = newValue;
            
            // Send update to backend
            this.getWebsocket().send(
                JSON.stringify({
                    type: 'devtools',
                    action: 'update_game_state',
                    variables: updatedVariables,
                })
            );
        },
        openGameStateEditor() {
            if (this.openWorldStateManager) {
                this.openWorldStateManager('scene', 'gamestate');
            }
        },
    },
}
</script>

<style scoped>
</style>
