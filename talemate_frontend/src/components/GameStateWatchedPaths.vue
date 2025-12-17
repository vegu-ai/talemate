<template>
    <v-card>
        <v-card-title class="text-subtitle-1">
            Watched Variables
        </v-card-title>
        <v-card-text>
            <div class="mb-3">
                <v-autocomplete
                    v-model="selectedPath"
                    :items="availablePaths"
                    label="Add path to watch"
                    density="compact"
                    variant="outlined"
                    hide-details
                    @update:model-value="onPathSelected"
                >
                    <template v-slot:append-inner>
                        <v-btn
                            icon="mdi-plus"
                            size="small"
                            variant="text"
                            :disabled="!selectedPath || watchedPaths.includes(selectedPath)"
                            @click="addPath"
                        ></v-btn>
                    </template>
                </v-autocomplete>
            </div>
            
            <v-table density="compact" v-if="watchedPaths.length > 0">
                <thead>
                    <tr>
                        <th class="text-left">Path</th>
                        <th class="text-right" style="width: 80px;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="path in watchedPaths" :key="path">
                        <td class="text-caption">{{ path }}</td>
                        <td class="text-right">
                            <v-btn
                                icon="mdi-close-circle-outline"
                                size="small"
                                variant="text"
                                color="delete"
                                @click="removePath(path)"
                            ></v-btn>
                        </td>
                    </tr>
                </tbody>
            </v-table>
            
            <v-alert v-else color="muted" density="compact" variant="text">
                No watched paths. Add paths above to watch them in Debug Tools.
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
        availablePaths: {
            type: Array,
            default: () => [],
        },
    },
    emits: ['update:watchedPaths', 'path-added'],
    data() {
        return {
            selectedPath: null,
        };
    },
    methods: {
        addPath() {
            if (this.selectedPath && !this.watchedPaths.includes(this.selectedPath)) {
                const newPaths = [...this.watchedPaths, this.selectedPath];
                this.$emit('update:watchedPaths', newPaths);
                this.$emit('path-added', this.selectedPath);
                this.selectedPath = null;
            }
        },
        removePath(path) {
            const newPaths = this.watchedPaths.filter(p => p !== path);
            this.$emit('update:watchedPaths', newPaths);
        },
        onPathSelected(value) {
            if (value && !this.watchedPaths.includes(value)) {
                this.addPath();
            }
        },
    },
}
</script>

<style scoped>
</style>
