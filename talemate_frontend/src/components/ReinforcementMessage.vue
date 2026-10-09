<template>
    <div class="reinforcement-container" @mouseenter="hovered = true" @mouseleave="hovered = false">
        <v-tooltip :text="tooltip" location="top" max-width="420">
            <template #activator="{ props }">
                <v-chip
                    v-bind="props"
                    class="reinforcement-chip clickable"
                    link
                    :color="getMessageColor('reinforcement')"
                    :aria-expanded="String(expanded)"
                    @click="toggle">
                    <v-icon class="mr-2">mdi-image-auto-adjust</v-icon>
                    <span class="reinforcement-kind">State Update</span>
                    <span class="reinforcement-separator">·</span>
                    <span class="reinforcement-label">{{ label }}</span>
                    <v-icon class="ml-1" size="small">{{ expanded ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
                </v-chip>
            </template>
        </v-tooltip>
        <v-btn
            v-show="hovered"
            class="ml-1"
            size="x-small"
            variant="text"
            icon="mdi-close"
            :disabled="locked"
            aria-label="Remove this state reinforcement from the history"
            @click="remove" />
        <div v-if="expanded" class="reinforcement-details">
            <div v-if="editing">
                <v-textarea
                    ref="textarea"
                    v-model="draft"
                    color="highlight1"
                    bg-color="surface"
                    density="compact"
                    rows="2"
                    max-rows="12"
                    auto-grow
                    persistent-hint
                    :hint="editHint"
                    @keydown.enter.exact.prevent="save"
                    @keydown.escape.prevent="cancelEdit"
                    @blur="cancelEdit" />
                <HistoryEditNotice :message-id="message.id" />
            </div>
            <template v-else>
                <div
                    ref="text"
                    class="reinforcement-text"
                    :class="{ clamped: !showAll }"
                    :style="getMessageStyle('reinforcement')"
                    @dblclick="startEdit">{{ message.text }}</div>
                <div class="reinforcement-footer">
                    <v-btn
                        v-if="overflowing || showAll"
                        class="reinforcement-more mr-2"
                        size="x-small"
                        variant="text"
                        :append-icon="showAll ? 'mdi-chevron-up' : 'mdi-chevron-down'"
                        @click="showAll = !showAll">{{ showAll ? 'Show less' : 'Show more' }}</v-btn>
                    <v-chip
                        v-show="hovered"
                        class="reinforcement-edit-hint"
                        size="x-small"
                        color="mutedheader"
                        variant="text">
                        <v-icon>mdi-pencil</v-icon>
                        {{ locked ? 'Editing locked' : 'Double-click to edit.' }}
                    </v-chip>
                </div>
            </template>
        </div>
    </div>
</template>

<script>
import HistoryEditNotice from './HistoryEditNotice.vue';

export default {
    name: 'ReinforcementMessage',
    components: {
        HistoryEditNotice,
    },
    props: {
        message: { type: Object, required: true },
        // the newest entry of its tracked state: an edit also becomes the state's answer
        latest: { type: Boolean, default: true },
        locked: Boolean,
    },
    inject: ['requestDeleteMessage', 'getWebsocket', 'getMessageColor', 'getMessageStyle'],
    data() {
        return {
            expanded: false,
            hovered: false,
            showAll: false,
            overflowing: false,
            editing: false,
            draft: '',
        };
    },
    computed: {
        subject() {
            return this.message.character || 'World';
        },
        label() {
            return `${this.subject} — ${this.message.question}`;
        },
        tooltip() {
            const action = this.expanded ? 'Click to collapse.' : 'Click to show the answer.';
            return `State Update for ${this.subject}: ${this.message.question} ${action}`;
        },
        editHint() {
            const keys = 'Enter to save, Shift+Enter for a new line, Esc to cancel.';
            if (this.latest) return `Saving also updates the tracked state's answer. ${keys}`;
            return `An earlier answer: saving changes only this entry. ${keys}`;
        },
    },
    watch: {
        'message.text'() {
            this.measure();
        },
        showAll(value) {
            if (!value) this.measure();
        },
    },
    methods: {
        toggle() {
            this.expanded = !this.expanded;
            if (!this.expanded) {
                this.editing = false;
                return;
            }
            this.measure();
        },
        measure() {
            // the fully shown answer is not clamped, so it cannot tell whether it overflows
            if (this.showAll) return;
            this.$nextTick(() => {
                const el = this.$refs.text;
                this.overflowing = !!el && el.scrollHeight > el.clientHeight + 1;
            });
        },
        startEdit() {
            if (this.locked) return;
            this.draft = this.message.text;
            this.editing = true;
            this.$nextTick(() => this.$refs.textarea?.focus());
        },
        cancelEdit() {
            if (!this.editing) return;
            this.editing = false;
            this.measure();
        },
        save() {
            const text = this.draft.trim();
            this.editing = false;
            if (text && text !== this.message.text) {
                this.getWebsocket().send(JSON.stringify({
                    type: 'scene_message',
                    action: 'edit',
                    id: this.message.id,
                    text,
                }));
            }
            this.measure();
        },
        remove() {
            this.requestDeleteMessage(this.message.id);
        },
    },
};
</script>

<style scoped>
.clickable { cursor: pointer; }
.reinforcement-container { margin-bottom: 14px; }
.reinforcement-chip { margin-left: 10px; max-width: calc(100% - 48px); }
.reinforcement-chip :deep(.v-chip__content) {
    min-width: 0;
    overflow: hidden;
}
.reinforcement-kind {
    flex-shrink: 0;
    font-weight: 600;
    font-size: 0.75em;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}
.reinforcement-separator {
    flex-shrink: 0;
    margin: 0 6px;
    opacity: 0.6;
}
.reinforcement-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
}
.reinforcement-details { margin: 6px 10px 0 22px; }
.reinforcement-text {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}
.reinforcement-text.clamped {
    display: -webkit-box;
    -webkit-line-clamp: 6;
    line-clamp: 6;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.reinforcement-footer {
    display: flex;
    align-items: center;
    min-height: 24px;
}
.reinforcement-more { margin-left: -8px; }
.reinforcement-edit-hint { margin-left: -8px; }
.reinforcement-more + .reinforcement-edit-hint { margin-left: 0; }
</style>
