<template>
    <v-card variant="text" v-if="hasRecentScenes()">
        <v-card-title class="ml-2">
            <v-icon size="x-small" class="mr-1" color="primary">mdi-folder</v-icon>
            Quick load
        </v-card-title>
        <!-- 
        horizontal scroll from config.recent_scenes.scenes
        if sceneLoadingAvailable, clicking the scene should load it

        scene object has the following properties:
        - name
        - path (path to load)
        - filename (filename to display, sans extension)
        - cover_image (cover image to request - asset id)
        - date (date to display, iso format)
        -->
        <v-card-text v-if="config != null">
            <div class="tiles">
                <div class="tile" v-for="(scene, index) in recentScenes()" :key="index">
                    <v-card :disabled="!sceneLoadingAvailable || sceneIsLoading" density="compact" elevation="7"  @click="loadScene(scene)" color="grey-darken-3" variant="outlined">
                        <v-card-title class="text-primary">
                            {{ filenameToTitle(scene.filename) }}

                            <v-menu>
                                <template v-slot:activator="{ props }">
                                    <v-btn 
                                    class="btn-menu"
                                    v-bind="props"
                                    color="primary" 
                                    icon 
                                    variant="text"
                                    size="small"><v-icon>mdi-dots-vertical</v-icon></v-btn>
                                </template>
                                <v-list density="compact">
                                    <v-list-item prepend-icon="mdi-backup-restore" @click="showBackupRestore(scene)">
                                        <v-list-item-title>Restore from Backup</v-list-item-title>
                                    </v-list-item>
                                    <v-divider></v-divider>
                                    <v-list-subheader>Remove</v-list-subheader>
                                    <v-list-item prepend-icon="mdi-table-large-remove" @click="removeFromRecentScenes(scene)">
                                        <v-list-item-title>Remove from Quick Load</v-list-item-title>
                                    </v-list-item>
                                    <v-list-item prepend-icon="mdi-file-remove-outline" @click="deleteScene(scene)">
                                        <v-list-item-title>Delete</v-list-item-title>
                                    </v-list-item>
                                </v-list>
                            </v-menu>


                        </v-card-title>
                        <v-card-subtitle class="text-grey-lighten-1">
                            {{ scene.name }}
                        </v-card-subtitle>
                        <v-card-text>
                            <div class="cover-image-placeholder">
                                <v-img cover v-if="scene.cover_image != null && coverImages[scene.cover_image.id] != null" :src="getCoverImageSrc(scene.cover_image.id)" class="portrait-image"></v-img>
                            </div>
                            <p class="text-caption text-center text-grey-lighten-1">{{ prettyDate(scene.date) }}</p>
                        </v-card-text>
                    </v-card>
                </div>
            </div>
        </v-card-text>
    </v-card>
    <ConfirmActionPrompt
        ref="deleteScenePrompt"
        actionLabel="Delete Scene"
        description="Are you sure you want to delete this scene?"
        icon="mdi-delete"
        color="delete"
        @confirm="(params) => deleteScene(params.scene, true)"
    ></ConfirmActionPrompt>

    <!-- Backup Restore Dialog -->
    <v-dialog v-model="backupRestoreDialog" max-width="600px">
        <v-card>
            <v-card-title>
                <v-icon class="mr-2" color="primary">mdi-backup-restore</v-icon>
                Restore
                <v-chip size="small" label color="highlight2" variant="tonal" class="ml-2">{{ selectedScene?.name }}</v-chip> 
                <v-chip size="small" label color="highlight5" variant="tonal" class="ml-2">{{ selectedScene?.filename }}</v-chip>
            </v-card-title>

            <v-card-text>

                <v-progress-circular v-if="loadingBackups" indeterminate color="primary" class="d-flex mx-auto"></v-progress-circular>

                <v-alert v-if="!loadingBackups" color="primary" icon="mdi-information-outline" density="compact" variant="tonal" class="mb-3 text-caption">
                    <div class="mb-1">
                        <strong>Earliest</strong> restores the initial scene state (revision 0)
                    </div>
                    <div class="mb-1">
                        <strong>Latest</strong> restores the most recent saved state
                    </div>
                    <div v-if="!filterDateInput">
                        Use the date/time filter below to restore to a specific point in time (closest match will be shown)
                    </div>
                    <div v-else>
                        Date filter is active - showing closest revision to your selected time
                    </div>
                </v-alert>

                <v-row class="mb-2">
                    <v-col cols="12">
                        <v-text-field
                            type="datetime-local"
                            v-model="filterDateInput"
                            label="Filter by date/time (optional)"
                            density="comfortable"
                            @update:modelValue="applyDateFilter"
                            hide-details
                        >
                            <template v-slot:append-inner>
                                <v-btn
                                    v-if="filterDateInput"
                                    @click="clearDateFilter"
                                    icon="mdi-close"
                                    variant="text"
                                    size="small"
                                    density="comfortable"
                                ></v-btn>
                            </template>
                        </v-text-field>
                    </v-col>
                </v-row>

                <div v-if="!loadingBackups && backupFiles.length === 0" class="text-center text-grey">
                    <v-icon size="48" class="mb-2">{{ filterDateInput ? 'mdi-calendar-remove' : 'mdi-folder-open-outline' }}</v-icon>
                    <p v-if="filterDateInput">
                        No revisions found near {{ new Date(filterDateInput).toLocaleString() }}.
                    </p>
                    <p v-else>No revisions found for this scene.</p>
                </div>

                <v-card v-for="(backup, idx) in backupFiles" :key="idx" variant="tonal" elevation="7" color="grey-darken-1" density="compact" class="mb-2">
                    <v-card-text class="text-muted">
                        <div class="d-flex align-center">
                            <v-icon class="mr-3" color="grey-lighten-3">{{ getBackupIcon(backup) }}</v-icon>
                            <div>
                                <div class="font-weight-medium text-grey-lighten-3">{{ getBackupLabel(backup) }}</div>
                                <div v-if="backup.timestamp" class="text-caption text-grey">
                                    {{ formatBackupDate(backup.timestamp) }} (rev {{ backup.rev }})
                                </div>
                            </div>
                        </div>
                    </v-card-text>
                    <v-card-actions>
                        <v-spacer></v-spacer>
                        <v-btn
                            color="primary"
                            :loading="restoringFromBackup"
                            @click="restoreFromBackupFile(backup)"
                            prepend-icon="mdi-backup-restore"
                        >
                            Restore
                        </v-btn>
                    </v-card-actions>
                </v-card>
                <v-alert v-if="backupFiles.length > 0" color="warning" icon="mdi-alert-outline" density="compact" class="text-caption mt-2" variant="tonal">
                    Restoring creates a new, unsaved scene from the selected revision. The original scene file will <strong>not</strong> be modified.
                </v-alert>
            </v-card-text>
            
            <v-card-actions>
                <v-btn text @click="closeBackupRestore" prepend-icon="mdi-close" color="cancel">Cancel</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>
<script>

import ConfirmActionPrompt from './ConfirmActionPrompt.vue';

export default {
    name: 'IntroRecentScenes',
    components: {
        ConfirmActionPrompt,
    },
    props: {
        sceneIsLoading: Boolean,
        sceneLoadingAvailable: Boolean,
        config: Object,
    },
    inject: ['requestAssets', 'getWebsocket', 'registerMessageHandler'],
    data() {
        return {
            coverImages: {},
            backupRestoreDialog: false,
            loadingBackups: false,
            restoringFromBackup: false,
            selectedScene: null,
            backupFiles: [],
            filterDateInput: null,
        }
    },
    emits: ['request-scene-load', 'request-backup-restore'],
    watch: {
        config(newVal) {
            if(newVal != null) {
                this.requestCoverImages();
            }
        },
    },
    methods: {

        filenameToTitle(filename) {
            // remove .json extension, replace _ with space, and capitalize first letter of each word

            filename = filename.replace('.json', '');

            return filename.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        },

        hasRecentScenes() {
            return this.config != null && this.config.recent_scenes != null && this.config.recent_scenes.scenes != null && this.config.recent_scenes.scenes.length > 0;
        },

        prettyDate(date) {
            // 2024-01-20T03:35:00.109492
            let d = new Date(date);
            return d.toLocaleString();

        },

        requestCoverImages() {
            if(this.config.recent_scenes != null) {
                if(this.config.recent_scenes.scenes != null) {
                    let coverImageIds = [];
                    for(let scene of this.config.recent_scenes.scenes) {
                        if(scene.cover_image != null) {
                            coverImageIds.push({
                                "path": scene.path,
                                "id": scene.cover_image.id,
                                "media_type": scene.cover_image.media_type,
                                "file_type": scene.cover_image.file_type,
                            });
                        }
                    }
                    this.requestAssets(coverImageIds);
                }
            }
        },

        loadScene(scene) {
            this.$emit("request-scene-load", scene.path)
        },
        recentScenes() {

            if(!this.config.recent_scenes) {
                return [];
            }

            return this.config.recent_scenes.scenes;
        },

        getCachedCoverImage(assetId) {
            if(this.coverImages[assetId]) {
                return this.coverImages[assetId];
            } else {
                return null;
            }
        },

        getCoverImageSrc(assetId) {
            if(this.coverImages[assetId]) {
                return 'data:'+this.coverImages[assetId].mediaType+';base64, '+this.coverImages[assetId].base64;
            } else {
                return null;
            }
        },

        deleteScene(scene, confirmed) {
            if(!confirmed) {
                this.$refs.deleteScenePrompt.initiateAction({scene: scene});
            } else {
                this.getWebsocket().send(JSON.stringify({
                    type: 'config',
                    action: 'delete_scene',
                    path: scene.path,
                }));
            }
        },

        removeFromRecentScenes(scene) {
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'remove_scene_from_recents',
                path: scene.path,
            }));
        },

        showBackupRestore(scene) {
            this.selectedScene = scene;
            this.backupRestoreDialog = true;
            this.loadingBackups = true;
            this.filterDateInput = null;
            this.backupFiles = [];

            // Request revisions from the server
            this.requestRevisions(scene.path);
        },

        closeBackupRestore() {
            this.backupRestoreDialog = false;
            this.selectedScene = null;
            this.backupFiles = [];
            this.loadingBackups = false;
            this.restoringFromBackup = false;
        },

        restoreFromBackupFile(backup) {
            if (!this.selectedScene || !backup) return;

            this.restoringFromBackup = true;

            // Emit restore request; frontend will pass through to loader
            this.$emit("request-backup-restore", {
                scenePath: this.selectedScene.path,
                backupPath: backup.path,
                rev: backup.rev,
            });

            this.closeBackupRestore();
        },

        getBackupLabel(backup) {
            if (backup.is_base) {
                return 'Restore Earliest (Base Snapshot)';
            } else if (backup.is_latest) {
                return 'Restore Latest (Latest Snapshot)';
            } else {
                return `Revision ${backup.rev ?? backup.name}`;
            }
        },

        getBackupIcon(backup) {
            if (backup.is_base) {
                return 'mdi-flag-outline';
            } else if (backup.is_latest) {
                return 'mdi-flag-checkered';
            } else {
                return 'mdi-file-outline';
            }
        },

        requestRevisions(scenePath) {
            const filterDate = this.filterDateInput ? new Date(this.filterDateInput).toISOString() : null;

            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'get_backup_files',
                scene_path: scenePath,
                filter_date: filterDate,
            }));
        },

        applyDateFilter() {
            // Request new data with filter
            if (this.selectedScene) {
                this.loadingBackups = true;
                this.backupFiles = [];
                this.requestRevisions(this.selectedScene.path);
            }
        },

        clearDateFilter() {
            this.filterDateInput = null;
            // Request data without filter
            if (this.selectedScene) {
                this.loadingBackups = true;
                this.backupFiles = [];
                this.requestRevisions(this.selectedScene.path);
            }
        },

        formatBackupName(filename) {
            // Convert "scene_backup_20250829_143022.json" to "29 Aug 2025 14:30:22"
            const match = filename.match(/_backup_(\d{8})_(\d{6})\.json$/);
            if (match) {
                const [, dateStr, timeStr] = match;
                const year = dateStr.substring(0, 4);
                const month = dateStr.substring(4, 6);
                const day = dateStr.substring(6, 8);
                const hour = timeStr.substring(0, 2);
                const minute = timeStr.substring(2, 4);
                const second = timeStr.substring(4, 6);
                
                const date = new Date(year, month - 1, day, hour, minute, second);
                return date.toLocaleString();
            }
            return filename.replace(/\.json$/, '');
        },

        formatBackupDate(timestamp) {
            return new Date(timestamp * 1000).toLocaleString();
        },

        formatFileSize(bytes) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        },

        handleMessage(data) {
            if(data.type === 'assets') {
                for(let id in data.assets) {
                    let asset = data.assets[id];
                    this.coverImages[id] = {
                        base64: asset.base64,
                        mediaType: asset.mediaType,
                    };
                }
            } else if(data.type == "config") {
                if(data.action == "delete_scene_complete") {
                    this.requestCoverImages();
                }
            } else if(data.type === 'backup') {
                console.debug('backup', data);
                if(data.action === 'backup_files') {
                    this.backupFiles = data.files || [];
                    this.loadingBackups = false;
                }
            }
        },
    },
    mounted() {
        this.requestCoverImages();
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>

<style scoped>

.cover-image-placeholder {
    position: relative;
    width: 100%;
    aspect-ratio: 3 / 4;
    min-height: clamp(200px, 25vw, 275px);
    background-color: transparent;
    background-image: url('/src/assets/logo-13.1-backdrop.png');
    background-repeat: no-repeat;
    background-position: center;
    background-size: cover;
    overflow: hidden;
}

.portrait-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.portrait-image :deep(img),
.portrait-image :deep(.v-img__img) {
    object-position: top !important;
}

.cover-image-placeholder :deep(.v-img__wrapper) {
    background-position: top center !important;
}

/* flud flex tiles with fixed width */
.tiles {
    display: flex;
    flex-wrap: wrap;
    justify-content: left;
    overflow: hidden;
}

.tile {
    flex: 0 0 275px;
    margin: 10px;
    max-width: 275px;
}

.v-card:disabled {
    opacity: 0.5;
}

.btn-menu {
    position: absolute;
    top: 0px;
    right: 0px;
}

</style>