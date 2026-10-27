<template>
    <v-card elevation="3" class="my-4" density="compact">
        <v-card-title class="text-body-medium text-time">
            <v-icon class="mr-2" size="small">mdi-clock-fast</v-icon>
            Time Passage
        </v-card-title>
        <v-card-text>
            <div v-if="!editing" class="d-flex align-center"
                 @dblclick="setEditing(true)"
                 @mouseenter="hovered = true"
                 @mouseleave="hovered = false">
                <span v-if="passage.title" class="text-body-large text-time mr-2">{{ passage.title }}</span>
                <span class="text-body-large">{{ passage.human }}</span>
                <span class="text-body-small text-muted ml-2" :class="{ 'hover-hidden': !hovered }">
                    <v-icon size="small">mdi-pencil</v-icon> double-click to edit
                </span>
                <v-spacer />
                <span :class="{ 'hover-hidden': !hovered }">
                    <ConfirmActionInline
                        :disabled="locked"
                        icon="mdi-close-box-outline"
                        color="delete"
                        action-label="Delete"
                        confirm-label="Confirm"
                        @confirm="deletePassage"
                    />
                </span>
            </div>
            <div v-else class="d-flex align-center">
                <v-number-input v-model="editAmount" :min="0" label="Amount"
                    style="max-width: 160px" hide-details="auto" density="compact" />
                <v-select v-model="editUnit" :items="units" label="Unit"
                    style="max-width: 160px" hide-details="auto" density="compact" class="ml-2" />
                <v-text-field v-model="editTitle" label="Chapter title" style="max-width: 260px"
                    hide-details="auto" density="compact" class="ml-2" />
                <v-btn class="ml-2" color="success" variant="text" size="small"
                    prepend-icon="mdi-content-save" @click="save" :disabled="locked">Save</v-btn>
                <v-btn class="ml-1" color="cancel" variant="text" size="small"
                    prepend-icon="mdi-cancel" @click="cancel">Cancel</v-btn>
            </div>
        </v-card-text>
    </v-card>
</template>

<script>
import ConfirmActionInline from './ConfirmActionInline.vue';

export default {
    name: 'WorldStateManagerTimePassageEntry',
    components: { ConfirmActionInline },
    props: {
        passage: Object,
        appBusy: Boolean,
        appReady: {
            type: Boolean,
            default: true,
        },
        busy: Boolean,
    },
    inject: ['getWebsocket'],
    data() {
        return {
            editing: false,
            hovered: false,
            editAmount: this.passage.amount,
            editUnit: this.passage.unit,
            editTitle: this.passage.title || '',
            units: ['minutes', 'hours', 'days', 'weeks', 'months', 'years'],
        };
    },
    computed: {
        locked() {
            return this.appBusy || !this.appReady || this.busy;
        }
    },
    methods: {
        setEditing(val) {
            if (this.locked) return;
            this.editing = val;
            if (val) {
                this.editAmount = this.passage.amount;
                this.editUnit = this.passage.unit;
                // seeded from the current value: the handler writes whatever
                // is sent, so an unseeded field would clear the title on save
                this.editTitle = this.passage.title || '';
            }
        },
        save() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_time_passage',
                history_index: this.passage.history_index,
                amount: this.editAmount,
                unit: this.editUnit,
                title: this.editTitle || null,
            }));
            this.editing = false;
        },
        cancel() {
            this.editing = false;
        },
        deletePassage() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_time_passage',
                history_index: this.passage.history_index,
            }));
        },
    },
};
</script>

<style scoped>
/* hidden, not removed: the row keeps the height of the Delete button */
.hover-hidden {
    visibility: hidden;
}
</style>
