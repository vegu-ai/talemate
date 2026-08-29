<template>
    <v-menu>
        <template v-slot:activator="{ props }">
            <v-btn
            v-bind="props"
            :disabled="disabled"
            color="primary"
            icon
            variant="text"
            :size="size"
            @click.stop><v-icon>{{ icon }}</v-icon></v-btn>
        </template>
        <v-list density="compact">
            <v-list-item prepend-icon="mdi-history" @click="openTimeline">
                <v-list-item-title>Timeline</v-list-item-title>
            </v-list-item>
            <v-divider></v-divider>
            <v-list-subheader>Remove</v-list-subheader>
            <v-list-item v-if="showRemoveFromQuickLoad" prepend-icon="mdi-table-large-remove" @click="removeFromRecentScenes">
                <v-list-item-title>Remove from Quick Load</v-list-item-title>
            </v-list-item>
            <v-list-item prepend-icon="mdi-file-remove-outline" @click="$emit('delete')">
                <v-list-item-title>Delete</v-list-item-title>
            </v-list-item>
        </v-list>
    </v-menu>
</template>

<script>
export default {
    name: 'SceneSaveContextMenu',
    props: {
        scenePath: String,
        sceneName: String,
        showRemoveFromQuickLoad: {
            type: Boolean,
            default: true,
        },
        disabled: Boolean,
        icon: {
            type: String,
            default: 'mdi-dots-vertical',
        },
        size: {
            type: String,
            default: 'small',
        },
    },
    inject: ['getWebsocket', 'openSceneTimeline'],
    emits: ['delete'],
    methods: {
        openTimeline() {
            this.openSceneTimeline({
                scenePath: this.scenePath,
                sceneName: this.sceneName,
            });
        },
        removeFromRecentScenes() {
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'remove_scene_from_recents',
                path: this.scenePath,
            }));
        },
    },
}
</script>
