<template>
    <v-dialog v-model="dialog" width="500" :persistent="true">
        <v-card>
            <v-card-title>
                <v-icon icon="mdi-alert-circle" class="text-error mr-2" size="small"></v-icon>
                Generation Error</v-card-title>
            <v-card-text>
                <p class="mb-2"><span class="text-primary">{{ client }}</span> <span class="text-muted" v-if="model">({{ model }})</span> encountered an error:</p>
                <v-alert type="error" variant="tonal" density="compact" class="mb-3">
                    {{ errorMessage }}
                    <span v-if="statusCode" class="text-muted"> (HTTP {{ statusCode }})</span>
                </v-alert>
                <p v-if="queue.length" class="text-muted text-caption mb-0">
                    <v-icon icon="mdi-layers" size="x-small" class="mr-1"></v-icon>
                    {{ queue.length }} more error{{ queue.length > 1 ? 's' : '' }} pending
                </p>
            </v-card-text>
            <v-card-actions>
                <v-btn :disabled="responding" @click="respond('cancel')" prepend-icon="mdi-cancel" color="delete">Cancel</v-btn>
                <v-tooltip location="top" text="Proceeds with an empty response, which may cause consistency issues.">
                    <template v-slot:activator="{ props }">
                        <v-btn v-bind="props" :disabled="responding" @click="respond('ignore')" prepend-icon="mdi-debug-step-over" color="warning" variant="text">Ignore</v-btn>
                    </template>
                </v-tooltip>
                <v-spacer></v-spacer>
                <v-btn :disabled="responding" @click="respond('retry')" prepend-icon="mdi-refresh" color="primary">Retry</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
export default {
    name: 'GenerationErrorDialog',
    data() {
        return {
            dialog: false,
            queue: [],
            requestId: null,
            client: null,
            model: null,
            statusCode: null,
            errorMessage: null,
            responding: false,
        }
    },
    inject: ['getWebsocket'],
    methods: {
        // Each concurrently failing generation gets its own error dialog and
        // must be answered individually - queue them so answering one shows
        // the next instead of orphaning it (its backend coroutine would wait
        // on a response forever).
        open(data) {
            if (this.dialog) {
                this.queue.push(data)
                return
            }
            this.display(data)
        },
        display(data) {
            this.requestId = data.request_id
            this.client = data.client
            this.model = data.model
            this.statusCode = data.status_code
            this.errorMessage = data.error_message
            this.responding = false
            this.dialog = true
        },
        close() {
            this.dialog = false
            this.requestId = null
            this.client = null
            this.model = null
            this.statusCode = null
            this.errorMessage = null
            this.responding = false
        },
        // Cancel instead of silently dropping: a generation can fail (and
        // register its dialog future) after the backend's point-in-time
        // sweep on scene load, and an unanswered future hangs its coroutine
        // forever. Answering an already-resolved request is a backend no-op.
        closeAll() {
            if (this.requestId) {
                this.sendResponse(this.requestId, 'cancel')
            }
            for (const item of this.queue) {
                this.sendResponse(item.request_id, 'cancel')
            }
            this.queue = []
            this.close()
        },
        sendResponse(requestId, action) {
            this.getWebsocket().send(JSON.stringify({
                type: 'generation_error_response',
                request_id: requestId,
                action: action,
            }));
        },
        respond(action) {
            this.responding = true
            this.sendResponse(this.requestId, action)
            if (this.queue.length) {
                this.display(this.queue.shift())
            } else {
                this.close()
            }
        },
    }
}
</script>
