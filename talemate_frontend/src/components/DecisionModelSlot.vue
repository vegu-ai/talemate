<template>
    <v-list-subheader class="text-uppercase">
        <v-icon class="mr-1">mdi-scale-balance</v-icon>
        Decision model
        <v-icon v-if="!enabled" :color="stateColor" size="10" class="ml-2 mr-1">mdi-checkbox-blank-circle</v-icon>
        <span v-if="headerLabel" class="text-none text-body-small" :class="{ 'ml-2': enabled }">
            {{ stateLabel }}
        </span>
        <v-tooltip v-if="failureText" :text="failureText" max-width="300">
            <template v-slot:activator="{ props }">
                <v-icon v-bind="props" color="error" size="14" class="ml-1">mdi-alert-circle</v-icon>
            </template>
        </v-tooltip>
        <v-tooltip :text="enabled ? 'Turn the decision model off' : 'Turn the decision model on'">
            <template v-slot:activator="{ props }">
                <v-btn v-bind="props" class="ml-2 mr-1" size="x-small" variant="tonal" density="comfortable" rounded="sm"
                    icon="mdi-power-standby" :loading="saving" :disabled="saving"
                    :aria-label="enabled ? 'Turn the decision model off' : 'Turn the decision model on'"
                    :aria-pressed="enabled" data-testid="decision-model-power"
                    @click.stop="toggle"></v-btn>
            </template>
        </v-tooltip>
        <v-tooltip text="Decision model settings">
            <template v-slot:activator="{ props }">
                <v-btn v-bind="props" class="mr-1" size="x-small" variant="tonal" density="comfortable" rounded="sm" icon="mdi-cogs"
                    aria-label="Decision model settings" data-testid="decision-model-settings"
                    @click.stop="openSettings"></v-btn>
            </template>
        </v-tooltip>
    </v-list-subheader>
    <v-list v-if="enabled" density="compact" class="py-0">
        <v-list-item class="py-0">
            <v-list-item-title class="text-body-small">
                <v-tooltip :text="detailText" location="left">
                    <template v-slot:activator="{ props }">
                        <v-icon v-bind="props" :color="stateColor" size="12" class="mr-1">mdi-checkbox-blank-circle</v-icon>
                    </template>
                </v-tooltip>
                {{ status.model }}
            </v-list-item-title>
            <v-list-item-subtitle v-if="incomplete" class="text-body-small mt-1">
                <span class="text-warning">{{ missing }}</span>
                <a href="#" class="ml-1 text-primary" data-testid="decision-model-finish-setup"
                    @click.prevent.stop="openSettings">Finish setup</a>
            </v-list-item-subtitle>
        </v-list-item>
    </v-list>
</template>

<script>
import { lastFailureText, missingText, providerName } from '@/utils/decisionModelText';

const STATES = {
    disabled: { color: 'muted', label: 'Off' },
    incomplete: { color: 'warning', label: 'Incomplete' },
    ready: { color: 'success', label: 'Configured' },
};

export default {
    name: 'DecisionModelSlot',
    props: {
        status: Object,
    },
    inject: ['openAppConfig', 'saveAppConfig'],
    data() {
        return { saving: false };
    },
    computed: {
        state() {
            return STATES[this.status.state];
        },
        stateColor() {
            return this.state.color;
        },
        stateLabel() {
            return this.state.label;
        },
        enabled() {
            return this.status.enabled;
        },
        incomplete() {
            return this.status.state === 'incomplete';
        },
        missing() {
            return missingText(this.status.missing);
        },
        // a working slot states itself with a green dot beside the model, the
        // way a client row does; a state that wants the user says so in words
        headerLabel() {
            return this.status.state !== 'ready';
        },
        detailText() {
            return `${this.stateLabel} · ${providerName(this.status.provider)} · ${this.status.timeout_seconds} s time limit`;
        },
        failureText() {
            return lastFailureText(this.status.last_failure);
        },
    },
    methods: {
        openSettings() {
            this.openAppConfig('settings', 'decision-model');
        },
        // the status broadcast arrives before the save is answered, so a click
        // after the answer reads the new state rather than repeating the old one
        toggle() {
            if (this.saving) {
                return;
            }
            const enabled = !this.enabled;
            const done = () => { this.saving = false; };
            this.saving = true;
            const requestId = this.saveAppConfig((config) => {
                config.decision_model.enabled = enabled;
            }, { label: 'decision model', onComplete: done, onError: done });
            if (!requestId) {
                done();
            }
        },
    },
}
</script>
