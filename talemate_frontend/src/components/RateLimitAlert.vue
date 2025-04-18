<template>
    <v-dialog v-model="dialog" width="500" :persistent="true" v-if="!waiting">
        <v-card>
            <v-card-title>
                <v-icon icon="mdi-speedometer" class="text-primary mr-2" size="small"></v-icon>
                Rate Limit Exceeded</v-card-title>
            <v-card-text class="text-muted">
                <p>The rate limit <span class="text-primary">({{ rateLimit }} requests / minute)</span> for <span class="text-primary">{{ client }}</span> has been exceeded. You can wait, or you can abort the generation.</p>
                <p>The rate limit will reset in <span class="text-primary">{{ resetTimeFormatted }}</span> seconds.</p>
            </v-card-text>
            <v-card-actions>
                <v-btn :disabled="aborting" @click="abort" prepend-icon="mdi-cancel" color="delete">Abort Generation</v-btn>
                <v-spacer></v-spacer>
                <v-btn :disabled="aborting" @click="wait" prepend-icon="mdi-clock" color="primary">Wait</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
    <v-snackbar v-model="waiting" location="top" v-if="waiting" :timeout="-1" color="mutedbg" @click.prevent="waiting = false;">
        <p>
            Waiting for rate limit reset... <span class="text-primary">{{ resetTimeFormatted }}</span>
        </p>
    </v-snackbar>
</template>

<script>
export default {
    name: 'RateLimitAlert',
    data() {
        return {
            dialog: false,
            client: null,
            resetTime: 0,
            rateLimit: 0,
            waiting: false,
            aborting: false,
        }
    },
    computed: {
        resetTimeFormatted() {
            return Math.round(this.resetTime)
        }
    },
    inject: ['getWebsocket'],
    methods: {
        open(client, resetTime, rateLimit) {
            this.client = client
            this.resetTime = resetTime
            this.rateLimit = rateLimit
            if(!this.waiting) {
                this.dialog = true
            }
        },
        close() {
            this.client = null
            this.resetTime = 0
            this.rateLimit = 0
            this.dialog = false
            this.waiting = false
            this.aborting = false
        },
        abort() {
            this.aborting = true
            this.getWebsocket().send(JSON.stringify({ type: 'interrupt' }));
        },
        wait() {
            this.waiting = true
        },
    }
}
</script>
