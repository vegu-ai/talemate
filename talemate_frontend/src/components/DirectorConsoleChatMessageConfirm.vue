<template>
    <div>
        <template v-if="!decision">
            <div class="d-flex align-center ga-2">
                <v-icon color="warning">mdi-alert</v-icon>
                <div class="text-caption font-weight-medium">Confirm action: {{ name || 'Unknown' }}</div>
                <v-spacer />
                <div class="text-caption" :class="{ 'text-error': timeLeft <= 30 }" v-if="timeLeft > 0">
                    {{ formattedTime }}
                </div>
            </div>
            <div class="mt-1" v-if="description">
                <DirectorConsoleChatMessageMarkdown :text="description" />
            </div>
            <div class="text-caption mt-2" v-else>A write action requires your confirmation to proceed.</div>
            <div class="d-flex ga-2 mt-2">
                <v-btn size="x-small" color="primary" :loading="confirming" @click="decide('confirm')">Confirm</v-btn>
                <v-btn size="x-small" color="delete" variant="text" :loading="confirming" @click="decide('reject')">Reject</v-btn>
            </div>
        </template>
        <template v-else>
            <div class="d-flex align-center ga-2">
                <v-icon :color="decision === 'confirm' ? 'success' : 'delete'">{{ decision === 'confirm' ? 'mdi-check-circle' : 'mdi-close-circle' }}</v-icon>
                <div class="text-caption font-weight-medium">action {{ name || 'Unknown' }} {{ decision === 'confirm' ? 'APPROVED' : 'REJECTED' }}</div>
            </div>
        </template>
    </div>
</template>

<script>
import DirectorConsoleChatMessageMarkdown from './DirectorConsoleChatMessageMarkdown.vue';
export default {
    name: 'DirectorConsoleChatMessageConfirm',
    components: { DirectorConsoleChatMessageMarkdown },
    props: {
        id: [String, Number],
        name: String,
        description: String,
        decision: String,
        confirming: Boolean,
        timer: {
            type: Number,
            default: 180,
        },
    },
    emits: ['decide'],
    data() {
        return {
            timeLeft: 0,
            countdownInterval: null,
        };
    },
    computed: {
        formattedTime() {
            const minutes = Math.floor(this.timeLeft / 60);
            const seconds = this.timeLeft % 60;
            return `${minutes}:${seconds.toString().padStart(2, '0')}`;
        },
    },
    mounted() {
        if (!this.decision) {
            this.startCountdown();
        }
    },
    beforeUnmount() {
        if (this.countdownInterval) {
            clearInterval(this.countdownInterval);
        }
    },
    watch: {
        decision(newDecision) {
            if (newDecision) {
                this.stopCountdown();
            }
        },
    },
    methods: {
        decide(decision) {
            this.$emit('decide', { id: this.id, decision });
            this.stopCountdown();
        },
        startCountdown() {
            this.timeLeft = this.timer;
            this.countdownInterval = setInterval(() => {
                this.timeLeft--;
                if (this.timeLeft <= 0) {
                    this.stopCountdown();
                }
            }, 1000);
        },
        stopCountdown() {
            if (this.countdownInterval) {
                clearInterval(this.countdownInterval);
                this.countdownInterval = null;
            }
        },
    },
}
</script>

<style scoped>
</style>


