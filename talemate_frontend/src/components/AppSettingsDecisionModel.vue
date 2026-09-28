<template>
    <v-row>
        <v-col cols="12" md="9">
            <div v-if="status?.state === 'ready'" class="d-flex align-center ga-2 mb-4 text-body-medium" data-testid="decision-model-configured">
                <v-icon color="success" size="12">mdi-checkbox-blank-circle</v-icon>
                Configured
                <span class="text-medium-emphasis">· {{ providerLabel }}</span>
            </div>
            <v-alert v-else :type="stateAlert.type" variant="tonal" density="compact" class="mb-4" data-testid="decision-model-state">
                <div class="text-body-medium">{{ stateAlert.text }}</div>
            </v-alert>

            <v-alert v-if="failureText" type="error" variant="tonal" density="compact" class="mb-4">
                <div class="text-body-medium">{{ failureText }}</div>
            </v-alert>

            <div data-setting-anchor="decision_model_enabled" class="mb-6">
                <v-switch color="primary" density="compact" hide-details
                    v-model="settings.enabled" label="Use a decision model"></v-switch>
                <p class="text-body-small text-medium-emphasis mt-1">
                    While it is on, the text a feature checks is sent to the provider below.
                    World State and Memory use it right away; Editor checks have their own switch.
                </p>
            </div>

            <div data-setting-anchor="decision_model_provider" class="mb-4">
                <v-select v-model="settings.provider" :items="providers" label="Provider" density="compact"
                    :hint="providerHint" persistent-hint></v-select>
            </div>

            <div v-if="isSystemOne" data-setting-anchor="decision_model_base_url" class="mb-4">
                <v-text-field v-model="settings.base_url" label="Server address" density="compact"
                    placeholder="https://api.typesafe.ai" :rules="[baseUrlRule]" hide-details="auto"
                    hint="For example https://api.typesafe.ai, or http://localhost:8009 for a server on this machine."
                    persistent-hint></v-text-field>
            </div>

            <div data-setting-anchor="decision_model_model" class="mb-4">
                <v-text-field v-model="settings.model" label="Model" density="compact"
                    :rules="[modelRule]" hide-details="auto" :hint="modelHint" persistent-hint></v-text-field>
            </div>

            <div data-setting-anchor="decision_model_credential">
                <ConfigWidgetUnifiedApiKey :config-path="credential.path"
                    :title="credential.title" :description="credentialDescription"
                    :required="!isSystemOne"
                    :app-config="config" />
            </div>

            <v-expansion-panels v-model="advancedPanel" data-setting-anchor="decision_model_advanced">
                <v-expansion-panel value="advanced" eager>
                    <v-expansion-panel-title>
                        <v-icon class="mr-2" color="primary" size="small">mdi-cog-outline</v-icon>
                        Advanced
                        <span class="text-medium-emphasis text-body-small ml-3">Time limit and input limits</span>
                    </v-expansion-panel-title>
                    <v-expansion-panel-text>
                        <div data-setting-anchor="decision_model_timeout" class="mb-4">
                            <v-text-field v-model.number="settings.timeout_seconds" label="Time limit (seconds)"
                                type="number" min="0.1" step="0.1" density="compact"
                                :rules="[timeoutRule]" hide-details="auto" persistent-hint
                                hint="How long to wait for an answer. Without one in time, the feature carries on as if the decision model were off."></v-text-field>
                        </div>
                        <v-row density="compact">
                            <v-col cols="12" sm="6" data-setting-anchor="decision_model_max_input_tokens">
                                <v-text-field v-model.number="settings.max_input_tokens" label="Input limit (tokens)"
                                    type="number" min="0" step="1000" density="compact"
                                    :rules="[limitRule]" hide-details="auto" persistent-hint
                                    hint="The largest request to send. 0 means no limit."></v-text-field>
                            </v-col>
                            <v-col cols="12" sm="6" data-setting-anchor="decision_model_max_question_input_tokens">
                                <v-text-field v-model.number="settings.max_question_input_tokens" label="Input limit per question (tokens)"
                                    type="number" min="0" step="1000" density="compact"
                                    :rules="[limitRule]" hide-details="auto" persistent-hint
                                    hint="The largest single question with its text. 0 means no limit."></v-text-field>
                            </v-col>
                        </v-row>
                        <div data-setting-anchor="decision_model_input_token_multiplier" class="mt-4">
                            <v-text-field v-model.number="settings.input_token_multiplier" label="Size estimate margin"
                                type="number" min="1" step="0.1" density="compact"
                                :rules="[multiplierRule]" hide-details="auto" persistent-hint
                                hint="Talemate estimates the size of a request before it sends it. A higher margin stops more oversize requests early, and some that would have fit."></v-text-field>
                        </div>
                    </v-expansion-panel-text>
                </v-expansion-panel>
            </v-expansion-panels>
        </v-col>
    </v-row>
</template>

<script>
import ConfigWidgetUnifiedApiKey from './ConfigWidgetUnifiedApiKey.vue';
import { PROVIDER_NAMES, lastFailureText, missingText, providerName } from '@/utils/decisionModelText';

const STATE_ALERTS = {
    unknown: {
        type: 'info',
        text: 'Waiting for Talemate to report the status.',
    },
    disabled: {
        type: 'info',
        text: 'Off. No feature asks the decision model anything.',
    },
    incomplete: {
        type: 'warning',
        text: 'On, but not ready yet.',
    },
};

const CREDENTIALS = {
    openrouter: { path: 'openrouter.api_key', title: 'OpenRouter API Key' },
    systemone: { path: 'decision_model.api_key', title: 'SystemOne API Key' },
};

export default {
    name: 'AppSettingsDecisionModel',
    components: {
        ConfigWidgetUnifiedApiKey,
    },
    props: {
        config: Object,
        status: Object,
    },
    data() {
        return {
            providers: Object.entries(PROVIDER_NAMES).map(([value, title]) => ({ title, value })),
            advancedPanel: null,
        };
    },
    computed: {
        settings() {
            return this.config.decision_model;
        },
        isSystemOne() {
            return this.settings.provider === 'systemone';
        },
        providerLabel() {
            return providerName(this.status?.provider);
        },
        providerHint() {
            return this.isSystemOne
                ? 'A compatible server you run yourself, or a hosted one such as TypeSafe.'
                : 'Uses your OpenRouter account.';
        },
        modelHint() {
            return this.isSystemOne
                ? 'The model name your server expects.'
                : 'The model name on OpenRouter. The default is typesafe/jev-1.13.';
        },
        stateAlert() {
            const alert = STATE_ALERTS[this.status?.state] || STATE_ALERTS.unknown;
            if (this.status?.state !== 'incomplete') {
                return alert;
            }
            return { ...alert, text: `${alert.text} ${missingText(this.status.missing)}` };
        },
        failureText() {
            return lastFailureText(this.status?.last_failure);
        },
        credential() {
            return CREDENTIALS[this.settings.provider];
        },
        credentialDescription() {
            if (this.isSystemOne) {
                return 'Only needed if your server asks for one. Hosted TypeSafe does.';
            }
            return 'Shared with the OpenRouter client and the API Keys page. Saving a key does not turn the decision model on.';
        },
        advancedValid() {
            return this.validTimeout(this.settings.timeout_seconds)
                && this.validLimit(this.settings.max_input_tokens)
                && this.validLimit(this.settings.max_question_input_tokens)
                && this.validMultiplier(this.settings.input_token_multiplier);
        },
    },
    watch: {
        advancedValid: {
            immediate: true,
            handler(valid) {
                if (!valid) {
                    this.advancedPanel = 'advanced';
                }
            },
        },
    },
    methods: {
        validBaseUrl(value) {
            if (!(value || '').trim()) {
                return true;
            }
            try {
                const url = new URL(value.trim());
                return ['http:', 'https:'].includes(url.protocol) && Boolean(url.hostname)
                    && !url.username && !url.password && !url.search && !url.hash
                    && !value.includes('?') && !value.includes('#');
            } catch {
                return false;
            }
        },
        baseUrlRule(value) {
            return this.validBaseUrl(value) || 'Enter an address that starts with http:// or https://, with no user name, password, ? or #.';
        },
        modelRule(value) {
            return this.validModel(value) || 'Enter a model name.';
        },
        timeoutRule(value) {
            return this.validTimeout(value) || 'Enter a number of seconds greater than zero.';
        },
        limitRule(value) {
            return this.validLimit(value) || 'Enter a whole number, 0 or more.';
        },
        multiplierRule(value) {
            return this.validMultiplier(value) || 'Enter a number of 1 or more.';
        },
        present(value) {
            return value !== '' && value !== null && value !== undefined;
        },
        validModel(value) {
            return (value || '').trim() !== '';
        },
        validTimeout(value) {
            const seconds = Number(value);
            return this.present(value) && Number.isFinite(seconds) && seconds > 0;
        },
        validLimit(value) {
            return this.present(value) && Number.isInteger(Number(value)) && Number(value) >= 0;
        },
        validMultiplier(value) {
            return this.present(value) && Number.isFinite(Number(value)) && Number(value) >= 1;
        },
        // AppSettings refuses the save rather than letting the backend reject the
        // whole config, which would block every other page's settings with it
        validate() {
            if (!this.validBaseUrl(this.settings.base_url)) {
                return { valid: false, error: 'Decision Model: enter a server address that starts with http:// or https://, with no user name, password, ? or #.' };
            }
            if (!this.validModel(this.settings.model)) {
                return { valid: false, error: 'Decision Model: enter a model name.' };
            }
            if (!this.validTimeout(this.settings.timeout_seconds)) {
                return { valid: false, error: 'Decision Model: the time limit must be a number of seconds greater than zero.' };
            }
            if (!this.validLimit(this.settings.max_input_tokens) || !this.validLimit(this.settings.max_question_input_tokens)) {
                return { valid: false, error: 'Decision Model: the input limits must be whole numbers, 0 or more.' };
            }
            if (!this.validMultiplier(this.settings.input_token_multiplier)) {
                return { valid: false, error: 'Decision Model: the size estimate margin must be 1 or more.' };
            }
            return { valid: true };
        },
    },
}
</script>
