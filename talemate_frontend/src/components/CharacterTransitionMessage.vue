<template>
    <div class="transition-container">
        <v-chip
            class="transition-chip"
            :class="{ clickable: activated }"
            :link="activated"
            :style="{ color: message.color || undefined }"
            :aria-expanded="activated ? String(expanded) : undefined"
            @click="toggle">
            <v-icon class="mr-2">{{ activated ? 'mdi-account-arrow-right' : 'mdi-account-arrow-left' }}</v-icon>
            <span>{{ label }}</span>
        </v-chip>
        <div v-if="activated && expanded" class="transition-details">
            <p class="text-medium-emphasis">{{ status }}</p>
            <p v-if="participants" class="text-medium-emphasis">Present at entry: {{ participants }}</p>
            <template v-if="message.transitions_enabled">
                <v-textarea
                    v-model="note"
                    class="mt-3"
                    label="Arrival Note (Optional)"
                    :hint="`How ${message.character} arrives. Saved when you leave the field.`"
                    rows="2"
                    auto-grow
                    variant="outlined"
                    :color="dirty ? 'dirty' : undefined"
                    :base-color="dirty ? 'dirty' : undefined"
                    :disabled="locked || !message.available"
                    @update:model-value="dirty = true"
                    @focus="onFocus"
                    @blur="onBlur" />
            </template>
        </div>
    </div>
</template>

<script>
const NOTE_SAVE_DELAY = 500;

export default {
    props: {
        message: { type: Object, required: true },
        locked: Boolean,
    },
    inject: ['getWebsocket'],
    data() {
        return {
            expanded: false,
            note: this.message.arrival_note || '',
            dirty: false,
            focused: false,
            saveTimer: null,
            saveWaiting: false,
        };
    },
    computed: {
        activated() {
            return this.message.kind === 'activated';
        },
        label() {
            return `${this.message.character} ${this.activated ? 'activated' : 'deactivated'}`;
        },
        status() {
            if (!this.message.returning) return 'First time in the scene.';
            if (this.message.absence_seconds == null) return 'Back in the scene. The time away is unknown.';
            if (!this.message.absence_seconds) return 'Back in the scene. No scene time passed while away.';
            return `Back after ${this.message.absence} away.`;
        },
        participants() {
            return (this.message.participants || []).join(', ');
        },
    },
    watch: {
        'message.arrival_note'(value) {
            const saved = value || '';
            if (!this.dirty) {
                this.note = saved;
            } else if (saved === this.note.trim()) {
                this.dirty = false;
                if (!this.focused) this.note = saved;
            }
        },
        locked(value) {
            if (!value && this.saveWaiting) this.save();
        },
    },
    methods: {
        toggle() {
            this.expanded = !this.expanded;
        },
        onFocus() {
            this.focused = true;
            this.saveWaiting = false;
            clearTimeout(this.saveTimer);
            this.saveTimer = null;
        },
        onBlur() {
            this.focused = false;
            clearTimeout(this.saveTimer);
            this.saveTimer = setTimeout(() => {
                this.saveTimer = null;
                this.save();
            }, NOTE_SAVE_DELAY);
        },
        save() {
            if (!this.dirty) return;
            if (this.note.trim() === (this.message.arrival_note || '')) {
                this.dirty = false;
                return;
            }
            if (this.locked || !this.message.available) {
                this.saveWaiting = true;
                return;
            }
            this.saveWaiting = false;
            this.getWebsocket().send(JSON.stringify({ type: 'scene_message', action: 'transition_note', id: this.message.id, text: this.note }));
        },
    },
    beforeUnmount() {
        clearTimeout(this.saveTimer);
    },
};
</script>

<style scoped>
.clickable { cursor: pointer; }
.transition-container { margin-bottom: 8px; }
.transition-chip { margin-left: 10px; }
.transition-details { margin: 8px 10px 0; }
.transition-details p { margin-bottom: 4px; }
</style>
