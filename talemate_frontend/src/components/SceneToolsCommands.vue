<template>
    <v-menu v-if="groups.length">
        <template v-slot:activator="{ props }">
            <v-progress-circular class="ml-1 mr-1" size="24" v-if="pendingRequestId" indeterminate="disable-shrink"
                color="secondary"></v-progress-circular>
            <v-btn v-else class="hotkey mx-1" v-bind="props" :disabled="disabled" color="primary" icon variant="text">
                <v-icon>mdi-console-line</v-icon>
                <v-tooltip activator="parent" location="top">Custom commands</v-tooltip>
            </v-btn>
        </template>
        <v-list density="compact">
            <v-list-subheader>Custom Commands</v-list-subheader>

            <v-menu v-for="group in groups" :key="group.menu" open-on-hover location="end">
                <template v-slot:activator="{ props }">
                    <v-list-item v-bind="props" @click.stop prepend-icon="mdi-console-line" append-icon="mdi-chevron-right" density="compact" :disabled="disabled">
                        <v-list-item-title>{{ group.menu }}</v-list-item-title>
                    </v-list-item>
                </template>
                <v-list density="compact">
                    <v-list-item v-for="command in group.commands" :key="command.name"
                        density="compact" :prepend-icon="command.icon" :disabled="disabled" @click="runCommand(command)">
                        <v-list-item-title>{{ command.label }}</v-list-item-title>
                    </v-list-item>
                </v-list>
            </v-menu>
        </v-list>
    </v-menu>

    <v-dialog v-model="dialog" max-width="600">
        <v-card>
            <v-card-title>{{ dialogCommand ? dialogCommand.label : '' }}</v-card-title>
            <v-card-text>
                <div v-for="field in dialogFields" :key="field.name">
                    <v-checkbox v-if="field.input === 'checkbox'" v-model="values[field.name]"
                        :label="field.name" color="primary" density="compact" hide-details></v-checkbox>
                    <v-number-input v-else-if="field.input === 'number'" v-model="values[field.name]"
                        :label="field.name" hide-details="auto"></v-number-input>
                    <v-textarea v-else-if="field.input === 'textarea'" v-model="values[field.name]"
                        :label="field.name" hint="One list item per line" rows="3" auto-grow></v-textarea>
                    <v-text-field v-else v-model="values[field.name]" :label="field.name"></v-text-field>
                </div>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="cancel" variant="text" @click="dialog = false">Cancel</v-btn>
                <v-btn color="primary" variant="text" prepend-icon="mdi-play" @click="submitDialog">Run</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import { newUuid } from '@/utils/uuid';
import { argFields, buildArgs, groupByMenu } from '@/utils/sceneCommands';

export default {
    name: 'SceneToolsCommands',
    props: {
        disabled: {
            type: Boolean,
            required: true,
        },
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
    data() {
        return {
            commands: [],
            scenePath: null,
            catalogRequested: false,
            pendingRequestId: null,
            dialog: false,
            dialogCommand: null,
            values: {},
        }
    },
    computed: {
        groups() {
            return groupByMenu(this.commands);
        },

        dialogFields() {
            return argFields(this.dialogCommand);
        },
    },
    methods: {
        requestCatalog() {
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_commands',
                action: 'request_catalog',
            }));
        },

        runCommand(command) {
            const fields = argFields(command);

            if (!fields.length) {
                this.sendRun(command, {});
                return;
            }

            this.dialogCommand = command;
            this.values = {};
            for (const field of fields) {
                this.values[field.name] = this.initialValue(field);
            }
            this.dialog = true;
        },

        initialValue(field) {
            if (field.input === 'checkbox') {
                return false;
            }
            if (field.input === 'number') {
                return null;
            }
            return '';
        },

        submitDialog() {
            this.sendRun(this.dialogCommand, buildArgs(this.dialogFields, this.values));
            this.dialog = false;
        },

        sendRun(command, args) {
            const requestId = newUuid();
            this.pendingRequestId = requestId;
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_commands',
                action: 'run',
                name: command.name,
                args: args,
                request_id: requestId,
            }));
        },

        handleMessage(data) {
            if (data.type === 'scene_commands') {
                if (data.action === 'catalog') {
                    this.commands = data.data.commands || [];
                    this.catalogRequested = true;
                } else if (data.action === 'operation_done' && this.pendingRequestId &&
                    (!data.request_id || data.request_id === this.pendingRequestId)) {
                    // a run that fails after dispatch is acked by the generic
                    // plugin machinery, which carries no request id
                    this.pendingRequestId = null;
                }
                return;
            }

            if (data.type === 'scene_status') {
                // a lost ack must not wedge the button, so any scene_status
                // may clear it
                this.pendingRequestId = null;
                const path = data.data.path || data.name;
                if (path !== this.scenePath) {
                    this.scenePath = path;
                    this.commands = [];
                    this.catalogRequested = false;
                }
                // the backend pushes the catalog on every registration, so one
                // request per scene is enough to cover the initial state
                if (!this.catalogRequested) {
                    this.catalogRequested = true;
                    this.requestCatalog();
                }
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>
