<template>
    <div>
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

        <v-row>
            <v-col cols="12" md="4" data-setting-anchor="decision_model_provider">
                <v-select v-model="settings.provider" :items="providers" label="Provider" density="compact"
                    :hint="providerHint" persistent-hint></v-select>
            </v-col>
            <v-col cols="12" md="8" data-setting-anchor="decision_model_model">
                <v-text-field v-if="isSystemOne" v-model="settings.model" label="Model" density="compact"
                    :rules="[modelRule]" hide-details="auto" :hint="modelHint" persistent-hint></v-text-field>
                <v-combobox v-else v-model="settings.model" :items="openRouterModelIds" label="Model" density="compact"
                    :loading="decisionModels === null" :rules="[modelRule]" hide-details="auto"
                    :hint="modelHint" persistent-hint>
                    <template v-slot:item="{ props: itemProps, internalItem }">
                        <v-list-item v-bind="itemProps" :subtitle="openRouterModelNames[internalItem.raw]"></v-list-item>
                    </template>
                </v-combobox>
            </v-col>
            <v-col v-if="isSystemOne" cols="12" data-setting-anchor="decision_model_base_url">
                <v-text-field v-model="settings.base_url" label="Server address" density="compact"
                    placeholder="https://api.typesafe.ai" :rules="[baseUrlRule]" hide-details="auto"
                    hint="For example https://api.typesafe.ai, or http://localhost:8009 for a server on this machine."
                    persistent-hint></v-text-field>
            </v-col>
        </v-row>

        <div data-setting-anchor="decision_model_credential" class="mt-4">
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
                    <v-row density="compact">
                        <v-col cols="12" sm="6" md="3" data-setting-anchor="decision_model_timeout">
                            <v-number-input v-model="settings.timeout_seconds" label="Time limit (seconds)"
                                :min="0.1" :step="0.1" :precision="null" control-variant="stacked" density="compact"
                                :rules="[timeoutRule]" hide-details="auto" persistent-hint
                                hint="Without an answer in time, the feature carries on without it."></v-number-input>
                        </v-col>
                        <v-col cols="12" sm="6" md="3" data-setting-anchor="decision_model_max_input_tokens">
                            <TokenBudgetInput v-model="settings.max_input_tokens" label="Input limit (tokens)"
                                :step="1000" :precision="null" control-variant="stacked" density="compact"
                                :rules="[limitRule]" hide-details="auto" persistent-hint
                                hint="The largest request. 0 means no limit." />
                        </v-col>
                        <v-col cols="12" sm="6" md="3" data-setting-anchor="decision_model_max_question_input_tokens">
                            <TokenBudgetInput v-model="settings.max_question_input_tokens" label="Input limit per question (tokens)"
                                :step="1000" :precision="null" control-variant="stacked" density="compact"
                                :rules="[limitRule]" hide-details="auto" persistent-hint
                                hint="The largest single question. 0 means no limit." />
                        </v-col>
                        <v-col cols="12" sm="6" md="3" data-setting-anchor="decision_model_input_token_multiplier">
                            <v-number-input v-model="settings.input_token_multiplier" label="Size estimate margin"
                                :min="1" :step="0.1" :precision="null" control-variant="stacked" density="compact"
                                :rules="[multiplierRule]" hide-details="auto" persistent-hint
                                hint="Multiplies the size estimate. Higher stops more oversize requests early."></v-number-input>
                        </v-col>
                    </v-row>
                </v-expansion-panel-text>
            </v-expansion-panel>
        </v-expansion-panels>

        <div class="d-flex align-center flex-wrap ga-2 mt-4" data-setting-anchor="decision_model_restore_defaults">
            <v-btn color="warning" variant="text" prepend-icon="mdi-backup-restore"
                :disabled="atDefaults" @click="restoreDefaults">Restore Defaults</v-btn>
            <span class="text-body-small text-medium-emphasis">
                Resets the provider, model and advanced settings. The switch and the API keys stay; Save applies the change.
            </span>
        </div>
    </div>
</template>

<script>
import ConfigWidgetUnifiedApiKey from './ConfigWidgetUnifiedApiKey.vue';
import TokenBudgetInput from './TokenBudgetInput.vue';
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
        TokenBudgetInput,
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
    props: {
        config: Object,
        status: Object,
    },
    data() {
        return {
            providers: Object.entries(PROVIDER_NAMES).map(([value, title]) => ({ title, value })),
            advancedPanel: null,
            // null while OpenRouter's list is on its way, empty when it could not be loaded
            decisionModels: null,
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
        defaults() {
            return this.config.decision_model_defaults;
        },
        atDefaults() {
            return Object.entries(this.defaults).every(([key, value]) => this.settings[key] === value);
        },
        openRouterModelIds() {
            return (this.decisionModels || []).map((model) => model.id);
        },
        openRouterModelNames() {
            return Object.fromEntries((this.decisionModels || []).map((model) => [model.id, model.name]));
        },
        modelHint() {
            if (this.isSystemOne) {
                return 'The model name your server expects.';
            }
            const fallback = `The default is ${this.defaults.model}.`;
            if (this.decisionModels === null) {
                return `The model name on OpenRouter. ${fallback}`;
            }
            if (this.decisionModels.length === 0) {
                return `Could not load OpenRouter's decision models; type the model name. ${fallback}`;
            }
            return `Pick one of OpenRouter's decision models, or type a name. ${fallback}`;
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
        restoreDefaults() {
            Object.assign(this.settings, this.defaults);
        },
        requestDecisionModels() {
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'request_decision_models',
                data: {},
            }));
        },
        handleMessage(message) {
            if (message.type === 'config' && message.action === 'decision_models') {
                this.decisionModels = message.data.models;
            } else if (message.type === 'app_config' && !this.decisionModels?.length) {
                // a reconnect or a save; the reply to the first request may never have arrived
                this.requestDecisionModels();
            }
        },
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
    created() {
        this.registerMessageHandler(this.handleMessage);
        this.requestDecisionModels();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>
