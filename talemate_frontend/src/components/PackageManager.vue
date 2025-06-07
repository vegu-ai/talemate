<template>
    <v-card>
        <v-card-title>Manage modules for <span class="text-primary">{{ scene.title }}</span></v-card-title>

        <v-card-subtitle>
            Modules will be installed to the scene.
        </v-card-subtitle>

        <v-card-text>
            <v-table>
                <thead>
                    <tr>
                        <th width="300">Name</th>
                        <th width="200">Author</th>
                        <th width="100">Status</th>
                        <th width="400">Actions</th>
                        <th width="*">Description</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="pkg in packageList" :key="pkg.registry">
                        <td>{{ pkg.name }}</td>
                        <td>{{ pkg.author }}</td>
                        <td>
                            <v-chip v-if="pkg.status === 'installed'" color="success" variant="outlined" size="small" label>Installed</v-chip>
                            <v-chip v-else color="muted" variant="outlined" size="small" label>Not Installed</v-chip>
                        </td>
                        <td>
                            <!--
                            {
                                "packages": [
                                    {
                                        "name": "Dynamic Storyline",
                                        "author": "Talemate",
                                        "description": "",
                                        "installable": true,
                                        "registry": "package/talemate/DynamicStoryline",
                                        "status": "installed",
                                        "package_properties": {
                                            "topic": {
                                                "module": "package/talemate/DynamicStoryline",
                                                "name": "topic",
                                                "label": "Topic",
                                                "description": "The overarching topic",
                                                "type": "str",
                                                "default": "",
                                                "value": null
                                            }
                                        }
                                    }
                                ]
                            }
                            -->
                            <v-btn :disabled="appBusy" v-if="pkg.status === 'installed'" color="delete" variant="text" @click="uninstallPackage(pkg.registry)" prepend-icon="mdi-close-circle-outline">Uninstall</v-btn>
                            <v-btn :disabled="appBusy" v-else color="primary" variant="text" @click="installPackage(pkg.registry)" prepend-icon="mdi-tray-arrow-down">Install</v-btn>
                            <v-btn :disabled="appBusy" v-if="pkg.status === 'installed'" color="primary" variant="text" @click="editPackageProperties(pkg)" prepend-icon="mdi-cog">Configure</v-btn>
                        </td>
                        <td class="text-muted">{{ pkg.description }}</td>
                    </tr>
                </tbody>
            </v-table>
        </v-card-text>
    </v-card>

    <v-dialog v-model="editPackagePropertiesDialog" :max-width="600" :contained="true" @keydown.esc="editPackagePropertiesDialog = false">
        <v-card>
            <v-card-title>Edit <span class="text-primary">{{ selectedPackage.name }}</span> Properties</v-card-title>
            <v-card-text>
                <v-form>
                    <div v-for="(prop, propName) in selectedPackage.package_properties" :key="propName">
                        <v-text-field v-model="prop.value" :label="prop.label" v-if="prop.type === 'str'" />
                        <v-text-field v-model="prop.value" :label="prop.label" v-if="prop.type === 'int'" type="number" />
                        <v-text-field v-model="prop.value" :label="prop.label" v-if="prop.type === 'float'" type="number" />
                        <v-checkbox v-model="prop.value" :label="prop.label" v-if="prop.type === 'bool'" />
                        <v-select v-model="prop.value" :label="prop.label" v-if="prop.type === 'list[str]'" :items="prop.choices" />
                    </div>
                </v-form>
            </v-card-text>
            <v-card-actions>
                <v-btn color="primary" @click="savePackageProperties">Save</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
export default {
    name: 'PackageManager',
    props: {
        visible: {
            type: Boolean,
            default: false,
        },
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
        visible(newVal) {
            if(newVal) {
                this.requestPackageList();
            }
        },
    },
    data() {
        return {
            packageList: [],
            editPackagePropertiesDialog: false,
            selectedPackage: null,
            requireRestart: false,
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],


    methods: {
        requestPackageList() {
            this.getWebsocket().send(JSON.stringify({
                type: 'package_manager',
                action: 'request_package_list',
            }));
        },

        editPackageProperties(pkg) {
            this.selectedPackage = {...pkg};
            this.editPackagePropertiesDialog = true;
        },

        savePackageProperties() {
            this.getWebsocket().send(JSON.stringify({
                type: 'package_manager',
                action: 'save_package_properties',
                package_registry: this.selectedPackage.registry,
                package_properties: this.selectedPackage.package_properties,
            }));
            this.editPackagePropertiesDialog = false;
        },

        installPackage(packageRegistry) {
            this.getWebsocket().send(JSON.stringify({
                type: 'package_manager',
                action: 'install_package',
                package_registry: packageRegistry,
            }));
        },

        uninstallPackage(packageRegistry) {
            this.getWebsocket().send(JSON.stringify({
                type: 'package_manager',
                action: 'uninstall_package',
                package_registry: packageRegistry,
            }));
        },
        handleMessage(data) {
            if(data.type !== 'package_manager')
                return;
            if(data.action === 'package_list') {
                this.packageList = data.data;
            }
        }
    },

    mounted() {
        this.requestPackageList();
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>