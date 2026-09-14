<template>
    <details class="character-transition my-3">
        <summary>{{ message.character }} {{ message.returning ? 'returns' : 'enters' }}</summary>
        <div class="pa-3">
            <p v-if="!message.available">This entry's history boundary is no longer available.</p>
            <p v-else class="transition-text">{{ message.text }}</p>
            <v-textarea v-model="note" label="Arrival note" rows="2" auto-grow variant="outlined" :disabled="locked || !message.available" />
            <v-btn size="small" variant="text" :disabled="locked || !message.available || note === message.arrival_note" @click="save">Save arrival note</v-btn>
            <p v-if="message.offscreen_status === 'pending'" role="status">Writing offscreen account…</p>
            <v-btn v-if="message.can_retry && message.offscreen_status === 'failed'" size="small" variant="text" :disabled="locked" @click="retry">Retry Offscreen Life</v-btn>
            <p v-if="message.offscreen_fact_id" class="text-body-small mt-2">Edit the offscreen account in World Editor → Facts ({{ message.offscreen_fact_id }}).</p>
        </div>
    </details>
</template>

<script>
export default {
    props: {
        message: { type: Object, required: true },
        locked: Boolean,
    },
    inject: ['getWebsocket'],
    data() { return { note: this.message.arrival_note || '' }; },
    watch: {
        'message.arrival_note'(value) { this.note = value || ''; },
    },
    methods: {
        save() {
            if (this.locked || !this.message.available) return;
            this.getWebsocket().send(JSON.stringify({ type: 'scene_message', action: 'transition_note', id: this.message.id, text: this.note }));
        },
        retry() {
            if (this.locked) return;
            this.getWebsocket().send(JSON.stringify({ type: 'scene_message', action: 'retry_offscreen', id: this.message.id }));
        },
    },
};
</script>

<style scoped>
summary { cursor: pointer; }
.transition-text { white-space: pre-wrap; margin-bottom: 1rem; }
</style>
