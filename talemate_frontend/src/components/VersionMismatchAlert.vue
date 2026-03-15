<template>
    <v-dialog v-model="dialog" width="550" :persistent="true">
        <v-card>
            <v-card-title class="bg-delete">
                <v-icon icon="mdi-alert-octagon" class="mr-2" size="small"></v-icon>
                Version Mismatch Detected
            </v-card-title>
            <v-card-text class="text-muted pt-4">
                <v-alert type="warning" color="delete" variant="tonal" density="compact" class="mb-4">
                    <template v-slot:text>
                        Talemate will likely not function correctly until this is resolved.
                    </template>
                </v-alert>
                <p>
                    The frontend version <span class="text-delete">({{ frontendVersion }})</span>
                    does not match the backend version <span class="text-delete">({{ backendVersion }})</span>.
                </p>
                <p class="mt-3">
                    This usually happens when you updated Talemate but forgot to rebuild the frontend, or your browser is serving a cached version.
                </p>
                <v-divider class="my-4"></v-divider>
                <p class="text-body-2">
                    <strong>To fix this:</strong>
                </p>
                <ul class="text-body-2 ml-4">
                    <li><strong>Browser cache:</strong> Hard refresh this page (<code class="bg-grey-darken-3 px-1">Ctrl+Shift+R</code> or <code class="bg-grey-darken-3 px-1">Cmd+Shift+R</code>)</li>
                    <li><strong>Git users:</strong> Run <code class="bg-grey-darken-3 px-1">update.bat</code> (Windows) or <code class="bg-grey-darken-3 px-1">update.sh</code> (Linux/Mac)</li>
                    <li><strong>Others:</strong> Do a fresh install</li>
                </ul>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn @click="dismiss" variant="text" color="muted">
                    Dismiss
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import { FRONTEND_VERSION } from '../constants/version.js';

export default {
    name: 'VersionMismatchAlert',
    data() {
        return {
            dialog: false,
            backendVersion: null,
        }
    },
    computed: {
        frontendVersion() {
            return FRONTEND_VERSION;
        }
    },
    methods: {
        open(backendVersion) {
            this.backendVersion = backendVersion;
            this.dialog = true;
        },
        close() {
            this.dialog = false;
        },
        dismiss() {
            this.close();
        }
    }
}
</script>
