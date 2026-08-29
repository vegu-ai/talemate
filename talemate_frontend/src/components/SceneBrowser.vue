<template>
    <v-card variant="text">
        <v-card-title class="d-flex align-center">
            <v-icon size="x-small" class="mr-2" color="primary">mdi-file-tree</v-icon>
            Scene Library
            <v-spacer></v-spacer>
            <v-tooltip text="Refresh" location="top">
                <template v-slot:activator="{ props }">
                    <v-btn v-bind="props" icon variant="text" size="small" :loading="loadingTree" @click="fetchTree">
                        <v-icon>mdi-refresh</v-icon>
                    </v-btn>
                </template>
            </v-tooltip>
        </v-card-title>
        <v-card-text>
            <v-text-field
                v-model="filter"
                density="compact"
                variant="underlined"
                prepend-inner-icon="mdi-magnify"
                label="Filter scenes"
                clearable
                hide-details
                class="mb-2"
            ></v-text-field>

            <v-alert v-if="tree != null && !hasContent" color="muted" variant="text" density="compact" icon="mdi-information-outline">
                No saved scenes yet. Import a scene or character card, or create a new scene to get started.
            </v-alert>

            <v-skeleton-loader v-else-if="tree == null" type="list-item@4"></v-skeleton-loader>

            <div v-else class="browser-scroll">
            <v-treeview
                :items="treeItems"
                item-title="title"
                item-value="id"
                density="compact"
                open-on-click
                activatable
                color="primary"
                v-model:opened="opened"
                :activated="activated"
                @update:activated="onActivated"
            >
                <template #prepend="{ item }">
                    <v-avatar v-if="item.type === 'project' && coverImageSrc(item.coverImage)" size="28" rounded="sm">
                        <v-img :src="coverImageSrc(item.coverImage)" cover></v-img>
                    </v-avatar>
                    <v-icon v-else-if="item.type === 'project'" size="small" color="primary">mdi-folder-outline</v-icon>
                    <v-icon v-else-if="item.type === 'save'" size="small" color="highlight7">mdi-script-text-outline</v-icon>
                    <v-icon v-else-if="item.type === 'characters'" size="small" color="persona">mdi-account-box-multiple-outline</v-icon>
                    <v-avatar v-else-if="item.type === 'card' && fileImages[item.path]" size="28" rounded="sm">
                        <v-img :src="fileImages[item.path]" cover position="top"></v-img>
                    </v-avatar>
                    <v-icon v-else-if="item.type === 'card'" size="small" color="persona">{{ item.mediaType === 'application/json' ? 'mdi-code-json' : 'mdi-card-account-details-outline' }}</v-icon>
                    <v-icon v-else-if="item.type === 'more'" size="small" color="muted">mdi-dots-horizontal</v-icon>
                    <v-icon v-else-if="item.type === 'meta'" size="small" color="muted">mdi-information-outline</v-icon>
                </template>
                <template #title="{ item }">
                    <div v-if="item.type === 'meta'" class="browser-row text-caption text-grey">
                        <v-icon size="x-small" class="mr-1">mdi-image-multiple-outline</v-icon>
                        {{ item.numAssets }} {{ item.numAssets === 1 ? 'asset' : 'assets' }}
                        <span class="mx-2">·</span>
                        <v-icon size="x-small" class="mr-1">mdi-graph-outline</v-icon>
                        {{ item.numNodes }} {{ item.numNodes === 1 ? 'node module' : 'node modules' }}
                    </div>
                    <div v-else class="browser-row">
                        <span :class="item.type === 'project' ? 'text-primary' : ''">{{ item.title }}</span>
                        <span v-if="item.subtitle" class="text-caption text-grey ml-2">{{ item.subtitle }}</span>
                    </div>
                </template>
                <template #append="{ item }">
                    <span v-if="item.modified" class="text-caption text-grey-darken-1 mr-2 d-none d-sm-inline">{{ prettyDate(item.modified) }}</span>
                    <span v-if="item.size !== undefined" class="text-caption text-grey-darken-1 mr-2 d-none d-md-inline">{{ prettySize(item.size) }}</span>
                    <SceneSaveContextMenu
                        v-if="item.type === 'save'"
                        :scene-path="item.path"
                        :scene-name="item.subtitle || item.filename"
                        :show-remove-from-quick-load="isRecentScene(item.path)"
                        :disabled="!connected"
                        size="x-small"
                        @delete="confirmDeleteFile(item)"
                    />
                    <v-tooltip v-else-if="item.type === 'card'" text="Delete character card" location="top">
                        <template v-slot:activator="{ props }">
                            <v-btn v-bind="props" icon variant="text" size="x-small" color="delete" @click.stop="confirmDeleteFile(item)">
                                <v-icon>mdi-file-remove-outline</v-icon>
                            </v-btn>
                        </template>
                    </v-tooltip>
                    <v-tooltip v-else-if="item.type === 'project'" text="Delete scene project" location="top">
                        <template v-slot:activator="{ props }">
                            <v-btn v-bind="props" icon variant="text" size="x-small" color="delete" @click.stop="openDeleteProjectDialog(item)">
                                <v-icon>mdi-folder-remove-outline</v-icon>
                            </v-btn>
                        </template>
                    </v-tooltip>
                </template>
            </v-treeview>
            </div>
        </v-card-text>

        <ConfirmActionPrompt
            ref="deleteFilePrompt"
            actionLabel="Delete file"
            description="Are you sure you want to delete {filename}?"
            icon="mdi-file-remove-outline"
            color="delete"
            :max-width="400"
            @confirm="(params) => deleteFile(params.path)"
        ></ConfirmActionPrompt>

        <v-dialog v-model="deleteProjectDialog" max-width="500" @keydown.esc="deleteProjectDialog = false">
            <v-card>
                <v-card-title class="headline">
                    <v-icon class="mr-2" size="x-small" color="delete">mdi-folder-remove-outline</v-icon>
                    Delete scene project
                </v-card-title>
                <v-card-text>
                    <p>
                        This will permanently delete the
                        <span class="text-primary">{{ deleteProjectTarget?.title }}</span>
                        project - all of its saved scenes, assets and history. This cannot be undone.
                    </p>
                    <p class="mt-3 text-caption text-grey">Type the project name to confirm.</p>
                    <v-text-field
                        v-model="deleteProjectConfirmation"
                        density="compact"
                        variant="underlined"
                        :placeholder="deleteProjectTarget?.title"
                        autofocus
                        hide-details
                        @keydown.enter="deleteProjectConfirmed && deleteProject()"
                    ></v-text-field>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn color="muted" variant="text" @click="deleteProjectDialog = false">Cancel</v-btn>
                    <v-btn color="delete" variant="text" :disabled="!deleteProjectConfirmed" prepend-icon="mdi-folder-remove-outline" @click="deleteProject">Delete project</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </v-card>
</template>

<script>
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import SceneSaveContextMenu from './SceneSaveContextMenu.vue';

const SAVE_DISPLAY_LIMIT = 10;
const CHARACTER_CARDS_ID = '$CHARACTER_CARDS$';

export default {
    name: 'SceneBrowser',
    components: {
        ConfirmActionPrompt,
        SceneSaveContextMenu,
    },
    props: {
        connected: Boolean,
        sceneLoadingAvailable: Boolean,
        visible: Boolean,
        config: Object,
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'isConnected'],
    emits: ['load-save', 'load-card'],
    data() {
        return {
            tree: null,
            loadingTree: false,
            filter: '',
            opened: [],
            activated: [],
            fileImages: {},
            requestedFileImages: [],
            showAllSaves: [],
            deleteProjectDialog: false,
            deleteProjectTarget: null,
            deleteProjectConfirmation: '',
        }
    },
    computed: {
        hasContent() {
            return this.tree != null && (this.tree.projects.length > 0 || this.tree.characters.length > 0);
        },
        deleteProjectConfirmed() {
            return this.deleteProjectTarget != null && this.deleteProjectConfirmation.trim() === this.deleteProjectTarget.title;
        },
        treeItems() {
            if (!this.tree) {
                return [];
            }

            const filter = (this.filter || '').toLowerCase();
            const items = [];

            for (const project of this.tree.projects) {
                const projectMatches = project.name.toLowerCase().includes(filter);

                let files = project.files.filter((file) => {
                    if (!filter || projectMatches) {
                        return true;
                    }
                    return file.filename.toLowerCase().includes(filter) ||
                        (file.scene_name || '').toLowerCase().includes(filter);
                }).map((file) => ({
                    id: file.path,
                    type: 'save',
                    title: file.relpath,
                    subtitle: file.scene_name,
                    path: file.path,
                    filename: file.filename,
                    modified: file.modified,
                    size: file.size,
                }));

                if (filter && !projectMatches && files.length === 0) {
                    continue;
                }

                // cap long save lists behind a "show all" row (newest first,
                // so the cap hides only older saves); filtering shows all matches
                if (!filter && files.length > SAVE_DISPLAY_LIMIT && !this.showAllSaves.includes(project.path)) {
                    const total = files.length;
                    files = files.slice(0, SAVE_DISPLAY_LIMIT);
                    files.push({
                        id: `${project.path}/$MORE$`,
                        type: 'more',
                        title: `Show all ${total} saves`,
                        projectPath: project.path,
                    });
                }

                // lead the expanded project with a metadata row (hidden while
                // filtering so search results stay clean)
                if (!filter) {
                    files.unshift({
                        id: `${project.path}/$META$`,
                        type: 'meta',
                        numAssets: project.num_assets,
                        numNodes: project.num_nodes,
                    });
                }

                items.push({
                    id: project.path,
                    type: 'project',
                    title: project.name,
                    subtitle: `${project.files.length} ${project.files.length === 1 ? 'save' : 'saves'}`,
                    path: project.path,
                    modified: project.modified,
                    coverImage: project.cover_image,
                    children: files,
                });
            }

            const cards = this.tree.characters.filter((card) => {
                return !filter || card.filename.toLowerCase().includes(filter);
            }).map((card) => ({
                id: card.path,
                type: 'card',
                title: card.relpath,
                path: card.path,
                modified: card.modified,
                size: card.size,
                mediaType: card.media_type,
            }));

            if (cards.length > 0) {
                items.push({
                    id: CHARACTER_CARDS_ID,
                    type: 'characters',
                    title: 'Character Cards',
                    subtitle: `${cards.length}`,
                    children: cards,
                });
            }

            return items;
        },
    },
    watch: {
        connected(connected) {
            if (connected) {
                this.fetchTree();
            }
        },
        visible(visible) {
            if (visible && this.isConnected()) {
                this.fetchTree();
            }
        },
        filter(filter) {
            // auto-expand groups while filtering so matches are visible
            if (filter) {
                this.opened = this.treeItems.map((item) => item.id);
            }
        },
        opened(opened) {
            if (opened.includes(CHARACTER_CARDS_ID)) {
                this.requestCardImages();
            }
        },
    },
    methods: {
        fetchTree() {
            if (!this.isConnected()) {
                return;
            }
            this.loadingTree = true;
            this.getWebsocket().send(JSON.stringify({ type: 'request_scenes_tree' }));
        },

        onActivated(activated) {
            // treat activation as a click-to-load; reset activation so the
            // same entry can be clicked again
            this.activated = [];
            if (!activated.length) {
                return;
            }

            const item = this.findItem(this.treeItems, activated[0]);
            if (!item) {
                return;
            }

            if (item.type === 'more') {
                this.showAllSaves.push(item.projectPath);
                return;
            }

            if (!this.sceneLoadingAvailable) {
                return;
            }

            if (item.type === 'save') {
                this.$emit('load-save', item.path);
            } else if (item.type === 'card') {
                this.$emit('load-card', item.path);
            }
        },

        findItem(items, id) {
            for (const item of items) {
                if (item.id === id) {
                    return item;
                }
                if (item.children) {
                    const found = this.findItem(item.children, id);
                    if (found) {
                        return found;
                    }
                }
            }
            return null;
        },

        confirmDeleteFile(item) {
            this.$refs.deleteFilePrompt.initiateAction({ path: item.path, filename: item.filename });
        },

        isRecentScene(path) {
            const recents = this.config?.recent_scenes?.scenes || [];
            return recents.some((scene) => scene.path === path);
        },

        deleteFile(path) {
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'delete_scene',
                path: path,
            }));
        },

        openDeleteProjectDialog(item) {
            this.deleteProjectTarget = item;
            this.deleteProjectConfirmation = '';
            this.deleteProjectDialog = true;
        },

        deleteProject() {
            if (!this.deleteProjectConfirmed) {
                return;
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'delete_scene_project',
                path: this.deleteProjectTarget.path,
            }));
            this.deleteProjectDialog = false;
            this.deleteProjectTarget = null;
        },

        requestCoverImages() {
            if (!this.tree) {
                return;
            }
            for (const project of this.tree.projects) {
                if (project.cover_image) {
                    this.requestFileImage(project.cover_image.path);
                }
            }
        },

        requestFileImage(path) {
            if (!path || this.fileImages[path] || this.requestedFileImages.includes(path) || !this.isConnected()) {
                return;
            }
            this.requestedFileImages.push(path);
            this.getWebsocket().send(JSON.stringify({
                type: 'request_file_image_data',
                file_path: path,
            }));
        },

        requestCardImages() {
            if (!this.tree) {
                return;
            }
            for (const card of this.tree.characters) {
                if (card.media_type !== 'application/json') {
                    this.requestFileImage(card.path);
                }
            }
        },

        coverImageSrc(coverImage) {
            return (coverImage && this.fileImages[coverImage.path]) || null;
        },

        prettyDate(date) {
            return new Date(date).toLocaleString();
        },

        prettySize(size) {
            if (size < 1024) {
                return `${size} B`;
            }
            if (size < 1024 * 1024) {
                return `${(size / 1024).toFixed(1)} KB`;
            }
            return `${(size / (1024 * 1024)).toFixed(1)} MB`;
        },

        handleMessage(data) {
            if (data.type === 'scenes_tree') {
                this.tree = data.data;
                this.loadingTree = false;
                this.requestCoverImages();
                if (this.opened.includes(CHARACTER_CARDS_ID)) {
                    this.requestCardImages();
                }
                return;
            }

            if (data.type === 'file_image_data') {
                if (data.image_data && this.requestedFileImages.includes(data.file_path)) {
                    this.fileImages[data.file_path] = data.image_data;
                }
                return;
            }

            if (data.type === 'config' && (data.action === 'delete_scene_complete' || data.action === 'delete_scene_project_complete')) {
                this.fetchTree();
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    mounted() {
        if (this.isConnected()) {
            this.fetchTree();
        }
    },
}
</script>

<style scoped>
.browser-row {
    display: flex;
    align-items: baseline;
    min-width: 0;
}

.browser-scroll {
    max-height: 65vh;
    overflow-y: auto;
}
</style>
