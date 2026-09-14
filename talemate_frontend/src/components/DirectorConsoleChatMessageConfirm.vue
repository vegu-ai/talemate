<template>
    <div>
        <template v-if="!decision">
            <div class="d-flex align-center ga-2">
                <v-icon color="warning">mdi-alert</v-icon>
                <div class="text-body-small font-weight-medium">Confirm action: {{ name || 'Unknown' }}</div>
                <v-spacer />
                <div class="text-body-small" :class="{ 'text-error': timeLeft <= 30 }" v-if="timeLeft > 0">
                    {{ formattedTime }}
                </div>
            </div>
            <div class="mt-1" v-if="description">
                <DirectorConsoleChatMessageMarkdown :text="description" />
            </div>
            <div class="text-body-small mt-2" v-else>A write action requires your confirmation to proceed.</div>
            <v-textarea v-if="editingInstructions" v-model="instructions" label="What should happen instead?" rows="2" auto-grow class="mt-2" :disabled="confirming" hint="Reject with instructions or Enter skips this call; Confirm applies it (clear text first); Reject and abort stops the batch." persistent-hint @keydown.enter="sendInstructions" />
            <div class="d-flex flex-wrap ga-2 mt-2">
                <v-btn size="x-small" color="primary" :disabled="confirming || hasInstructions" :loading="confirming && !hasInstructions" @click="decide('confirm')">Confirm</v-btn>
                <v-btn size="x-small" color="delete" variant="text" :disabled="confirming" @click="decide('reject')">Reject and abort</v-btn>
                <v-btn v-if="!editingInstructions" size="x-small" variant="text" :disabled="confirming" @click="editingInstructions = true">Reject with instructions</v-btn>
                <v-btn v-else size="x-small" color="primary" :disabled="confirming || !hasInstructions" :loading="confirming && hasInstructions" @click="decide('reject_with_instructions')">Reject with instructions</v-btn>
            </div>
        </template>
        <template v-else>
            <div class="d-flex align-center ga-2">
                <v-icon :color="decision === 'confirm' ? 'success' : 'delete'">{{ decision === 'confirm' ? 'mdi-check-circle' : 'mdi-close-circle' }}</v-icon>
                <div class="text-body-small font-weight-medium">action {{ name || 'Unknown' }} {{ decisionLabel }}</div>
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
            editingInstructions: false,
            instructions: '',
        };
    },
    computed: {
        hasInstructions() {
            return Boolean(this.instructions.trim());
        },
        decisionLabel() {
            if (this.decision === 'confirm') return 'APPROVED';
            if (this.decision === 'timed_out') return 'TIMED OUT';
            if (this.decision === 'interrupted') return 'INTERRUPTED';
            if (this.decision === 'reject_with_instructions') return 'SKIPPED — instructions sent';
            return 'REJECTED';
        },
        formattedTime() {
            const minutes = Math.floor(this.timeLeft / 60);
            const seconds = this.timeLeft % 60;
            return `${minutes}:${seconds.toString().padStart(2, '0')}`;
        },
    },
    mounted() {
        if (!this.decision && this.timer > 0) {
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
        sendInstructions(event) {
            event.stopPropagation();
            if (event.shiftKey || event.isComposing) return;
            event.preventDefault();
            this.decide('reject_with_instructions');
        },
        decide(decision) {
            if (this.confirming || (decision === 'confirm' && this.hasInstructions) || (decision === 'reject_with_instructions' && !this.hasInstructions)) return;
            this.$emit('decide', { id: this.id, decision, instructions: decision === 'reject_with_instructions' ? this.instructions.trim() : '' });
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
