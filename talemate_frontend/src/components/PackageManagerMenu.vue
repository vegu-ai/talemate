<template>
    <v-alert v-if="appBusy" color="muted" variant="text">
        Scene is currently busy - please wait for it to finish its current task(s) before installing or uninstalling packages.
        <v-progress-linear color="primary" height="2" indeterminate class="mt-2"></v-progress-linear>
    </v-alert>
    <v-alert v-if="requireRestart" type="warning" variant="text">
        One or more recently installed/uninstalled modules require a scene reload. Make sure you save progress before reloading.
    </v-alert>
    <v-list-item v-if="requireRestart">
        <v-btn :disabled="appBusy" block color="primary" @click="reloadScene()" prepend-icon="mdi-reload" variant="tonal">Reload Scene</v-btn>
    </v-list-item>
</template>

<script>
export default {
    name: 'PackageManagerMenu',
    props: {
        scene: {
            type: Object,
            required: true,
        },
        appBusy: {
            type: Boolean,
            default: false,
        },
    },

    watch: {
        scene(newVal, oldVal) {
            if(newVal?.data?.path !== oldVal?.data?.path) {
                this.requireRestart = false;
            }
        },
    },

    data() {
        return {
            packageList: [],
            requireRestart: false,
        }
    },

    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],

    methods: {
        reloadScene() {
            if(!this.scene?.data?.saved) {
                if(!confirm("The current scene has unsaved changes. Are you sure you want to reload the scene?")) {
                    return;
                }
            }

            this.getWebsocket().send(JSON.stringify({ type: 'load_scene', file_path: this.scene.data.path }));
            this.requireRestart = false;
        },

        checkRequireRestart(pkg) {
            if(!pkg.restart_scene_loop) {
                return false;
            }
            if(!pkg.configured) {
                return false;
            }
            return true;
        },

        handleMessage(data) {
            if(data.type !== 'package_manager')
                return;

            if(data.action === 'package_list') {
                this.packageList = data.data;
            } else if(data.action === 'installed_package') {
                this.requireRestart = this.checkRequireRestart(data.data.package);
            } else if(data.action === 'uninstalled_package') {
                this.requireRestart = data.data.package.restart_scene_loop;
            } else if(data.action === 'updated_package') {
                this.requireRestart = this.checkRequireRestart(data.data.package);
            }
        }
    },

    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>