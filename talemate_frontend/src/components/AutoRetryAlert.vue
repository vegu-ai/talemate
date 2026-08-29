<template>
    <v-snackbar v-model="active" location="top" :timeout="-1" color="mutedbg" class="auto-retry-alert">
        <v-progress-circular indeterminate size="16" width="2" color="primary" class="mr-2"></v-progress-circular>
        <span class="text-primary">{{ client }}</span>: {{ message }} — retrying
        <span v-if="wait > 0">in {{ wait }}s </span>({{ attempt }}/{{ total }})
        <template v-slot:actions>
            <v-btn :disabled="aborting || closing" color="delete" variant="text" prepend-icon="mdi-cancel" @click="abort">Abort</v-btn>
        </template>
    </v-snackbar>
</template>

<script>
// fast retry sequences (an instant retry that immediately succeeds) can open
// and close within the snackbar's own transition - hold it on screen long
// enough to be readable
const MIN_VISIBLE_MS = 2500;

export default {
    name: 'AutoRetryAlert',
    data() {
        return {
            active: false,
            client: null,
            generationId: null,
            message: '',
            attempt: 0,
            total: 0,
            wait: 0,
            aborting: false,
            closing: false,
            openedAt: 0,
            closeTimer: null,
            countdownTimer: null,
        }
    },
    inject: ['getWebsocket'],
    methods: {
        open(data) {
            if (this.closeTimer) {
                clearTimeout(this.closeTimer)
                this.closeTimer = null
            }
            // a handoff to another retry sequence's content starts a fresh
            // readability window
            if (!this.active || data.generation_id !== this.generationId) {
                this.openedAt = Date.now()
            }
            this.client = data.client
            this.generationId = data.generation_id
            this.message = data.message
            this.attempt = data.attempt
            this.total = data.total
            this.wait = data.wait || 0
            this.aborting = false
            this.closing = false
            this.active = true
            this.startCountdown()
        },
        startCountdown() {
            this.stopCountdown()
            if (this.wait <= 0) {
                return
            }
            this.countdownTimer = setInterval(() => {
                if (this.wait > 1) {
                    this.wait -= 1
                } else {
                    this.wait = 0
                    this.stopCountdown()
                }
            }, 1000)
        },
        stopCountdown() {
            if (this.countdownTimer) {
                clearInterval(this.countdownTimer)
                this.countdownTimer = null
            }
        },
        close(generationId = null, immediate = false) {
            // with concurrent generations, one sequence finishing must not
            // hide another sequence's live retry state
            if (generationId && this.generationId && generationId !== this.generationId) {
                return
            }
            this.aborting = false
            // the sequence is over - an abort during the readability linger
            // would have nothing to act on
            this.closing = true
            this.stopCountdown()
            // keep the content fields - clearing them would blank the text
            // while the snackbar is still fading out
            const remaining = this.openedAt + MIN_VISIBLE_MS - Date.now()
            if (immediate || remaining <= 0) {
                this.active = false
                return
            }
            if (this.closeTimer) {
                clearTimeout(this.closeTimer)
            }
            this.closeTimer = setTimeout(() => {
                this.active = false
                this.closeTimer = null
            }, remaining)
        },
        abort() {
            this.aborting = true
            // the interrupt cancels any in-flight generation; the dedicated
            // abort message latches on the displayed retry sequence so the
            // abort survives even when other websocket actions reset the
            // scene's cancel flag
            this.getWebsocket().send(JSON.stringify({ type: 'auto_retry_abort', client: this.client, generation_id: this.generationId }));
            this.getWebsocket().send(JSON.stringify({ type: 'interrupt' }));
        },
    },
    beforeUnmount() {
        this.stopCountdown()
        if (this.closeTimer) {
            clearTimeout(this.closeTimer)
        }
    },
}
</script>

<style scoped>
/* sit below the top-center status snackbar so the two never overlap */
.auto-retry-alert :deep(.v-snackbar__wrapper) {
    margin-top: 64px;
}
</style>
