<template>
  <v-form ref="form">

    <!-- SIMPLE MODE — the reduced field set used by the onboarding wizard -->
    <template v-if="simple">
      <v-alert v-if="meta.experimental" type="warning" variant="text" density="compact" icon="mdi-flask" class="mb-2">{{ meta.experimental }}</v-alert>
      <v-row>
        <v-col cols="6">
          <v-text-field :model-value="typeTitle" label="Client Type" readonly density="compact"></v-text-field>
        </v-col>
        <v-col cols="6">
          <v-text-field v-model="nameDraft" @blur="commitName" @keyup.enter="commitName" label="Client Name" :rules="nameRules" density="compact"></v-text-field>
        </v-col>
      </v-row>
      <v-row v-if="requiresAPIUrl || meta.enable_api_auth">
        <v-col :cols="requiresAPIUrl && meta.enable_api_auth ? 7 : 12">
          <v-text-field v-if="requiresAPIUrl" v-model="values.api_url" :rules="[rules.required]" label="API URL" density="compact"></v-text-field>
        </v-col>
        <v-col cols="5" v-if="requiresAPIUrl && meta.enable_api_auth">
          <v-text-field type="password" v-model="values.api_key" label="API Key" density="compact"></v-text-field>
        </v-col>
      </v-row>
      <ConfigWidgetUnifiedApiKey v-if="unifiedApiKeyPath" :config-path="unifiedApiKeyPath"
        :title="meta.title + ' API Key'" :description="unifiedApiKeyDescription" :app-config="config" />
      <v-combobox v-if="meta.manual_model && modelChoices" v-model="values.model" :items="modelChoices" label="Model" density="compact"></v-combobox>
      <v-text-field v-else-if="meta.manual_model" v-model="values.model" label="Manually specify model name" density="compact"></v-text-field>
    </template>

    <!-- FULL MODE -->
    <v-expansion-panels v-else v-model="openPanels" variant="accordion" multiple>

      <!-- GENERAL -->
      <v-expansion-panel value="general">
        <v-expansion-panel-title>
          <v-icon class="mr-2" color="primary" size="small">mdi-tune</v-icon> General
        </v-expansion-panel-title>
        <v-expansion-panel-text>
          <v-alert v-if="meta.experimental" type="warning" variant="text" density="compact" icon="mdi-flask" class="mb-2">{{ meta.experimental }}</v-alert>
          <v-row>
            <v-col cols="6">
              <v-text-field :model-value="typeTitle" label="Client Type" readonly density="compact"
                messages="The client type is picked when the client is added and cannot be changed afterwards."></v-text-field>
            </v-col>
            <v-col cols="6" data-setting-anchor="client_name">
              <v-text-field v-model="nameDraft" @blur="commitName" @keyup.enter="commitName" label="Client Name" :rules="nameRules" density="compact"></v-text-field>
            </v-col>
          </v-row>

          <!-- API URL AND KEY -->
          <v-row v-if="requiresAPIUrl || meta.enable_api_auth" data-setting-anchor="api_url">
            <v-col :cols="requiresAPIUrl && meta.enable_api_auth ? 7 : 12">
              <v-text-field v-if="requiresAPIUrl" v-model="values.api_url" :rules="[rules.required]" label="API URL" density="compact"></v-text-field>
            </v-col>
            <v-col cols="5" v-if="requiresAPIUrl && meta.enable_api_auth">
              <v-text-field type="password" v-model="values.api_key" label="API Key" density="compact"></v-text-field>
            </v-col>
          </v-row>

          <ConfigWidgetUnifiedApiKey v-if="unifiedApiKeyPath" :config-path="unifiedApiKeyPath"
            :title="meta.title + ' API Key'" :description="unifiedApiKeyDescription" :app-config="config" />

          <!-- MODEL -->
          <v-combobox v-if="meta.manual_model && modelChoices" v-model="values.model" :items="modelChoices" label="Model" density="compact"></v-combobox>
          <v-text-field v-else-if="meta.manual_model" v-model="values.model" label="Manually specify model name" density="compact"
            hint="It looks like we're unable to retrieve the model name automatically. The model name is used to match the appropriate prompt template. This is likely only important if you're locally serving a model."></v-text-field>
          <ModelExpectationsPanel compact class="mb-2" />

          <!-- EXTRA FIELDS WITHOUT A GROUP -->
          <UxField v-for="field in generalExtraFields" :key="field.name" :field="field"
            :model-value="values[field.name]" @update:model-value="(v) => setValue(field.name, v)" :app-config="config" />

          <v-row class="mt-1">
            <v-col cols="4" data-setting-anchor="max_token_length">
              <v-number-input v-model="values.max_token_length" label="Context Length" :rules="rulesMaxTokenLength" :step="64"></v-number-input>
            </v-col>
            <v-col v-if="contextLengthWarning" cols="12" class="pt-0">
              <v-alert type="warning" variant="tonal" density="compact" icon="mdi-alert-outline">{{ contextLengthWarning }}</v-alert>
            </v-col>

            <!-- PROMPT TEMPLATE -->
            <v-col cols="8" v-if="promptTemplateAvailable" data-setting-anchor="prompt_template">
              <v-autocomplete ref="promptTemplateComboBox" :label="'Prompt Template for ' + modelName"
                :model-value="templateInfo.template_file" @update:model-value="setPromptTemplate" :items="promptTemplates">
                <template #selection="{ item }">
                  <span class="text-truncate">{{ item }}</span>
                </template>
              </v-autocomplete>
              <v-card elevation="3" :color="(templateInfo.has_prompt_template ? 'primary' : 'warning')" variant="tonal">
                <v-card-text v-if="!waitingForTemplateSelection">
                  <div class="text-body-small" v-if="!templateInfo.has_prompt_template">No matching LLM prompt template found. Using default.</div>
                  <div class="prompt-template-preview">{{ templateInfo.prompt_template_example }}</div>
                </v-card-text>
                <v-card-text v-else>
                  <div class="text-body-small" v-if="!values.lock_template">Please select a prompt template to use for this client.</div>
                  <div class="text-body-small" v-else>Please select a prompt template to lock for this client.</div>
                </v-card-text>
                <v-card-actions v-if="!waitingForTemplateSelection">
                  <v-btn @click.stop="determineBestTemplate" prepend-icon="mdi-web-box">Determine via HuggingFace</v-btn>
                  <v-btn @click.stop="openLLMTemplates" prepend-icon="mdi-file-cog-outline">Manage Templates</v-btn>
                </v-card-actions>
              </v-card>
              <v-checkbox :model-value="values.lock_template" @update:model-value="lockTemplateChanged"
                hint="If checked, the prompt template will not longer automatically update." density="compact" color="primary">
                <template v-slot:label>
                  <v-icon color="muted" class="mr-1">mdi-sort-variant-lock</v-icon> Lock Template
                </template>
              </v-checkbox>
            </v-col>
          </v-row>
        </v-expansion-panel-text>
      </v-expansion-panel>

      <!-- COERCION -->
      <v-expansion-panel value="coercion" v-if="canBeCoerced" data-setting-anchor="coercion">
        <v-expansion-panel-title>
          <v-icon class="mr-2" color="primary" size="small">mdi-account-lock-open</v-icon> Coercion
        </v-expansion-panel-title>
        <v-expansion-panel-text>
          <v-alert icon="mdi-account-lock-open" density="compact" class="text-medium-emphasis" variant="text">
            <div>
              If set, this text will be prepended to every LLM response, attempting to enforce compliance with the request.
              <p>
                <v-chip label size="small" color="primary" @click.stop="values.double_coercion = 'Certainly: '">Certainly: </v-chip> or <v-chip @click.stop="values.double_coercion = 'Absolutely! here is exactly what you asked for: '" color="primary" size="small" label>Absolutely! here is exactly what you asked for: </v-chip> are good examples.
              </p>
              The tone of this coercion can also affect the tone of the rest of the response.
            </div>
            <v-divider class="mb-2 mt-2"></v-divider>
            <div>
              The longer the coercion, the more likely it will coerce the model to accept the instruction, but it may also make the response less natural or affect accuracy. <span class="text-warning">Only set this if you are actually getting hard refusals from the model.</span>
            </div>
          </v-alert>
          <v-textarea v-model="values.double_coercion" rows="2" max-rows="3" auto-grow label="Coercion" placeholder="Certainly: " class="mt-1"></v-textarea>
        </v-expansion-panel-text>
      </v-expansion-panel>

      <!-- ADVANCED -->
      <v-expansion-panel value="advanced" data-setting-anchor="advanced">
        <v-expansion-panel-title>
          <v-icon class="mr-2" color="primary" size="small">mdi-cog-outline</v-icon> Advanced
        </v-expansion-panel-title>
        <v-expansion-panel-text>
          <!-- INFERENCE PRESETS -->
          <v-row>
            <v-col cols="6">
              <v-select label="Inference Presets" :items="availablePresets" v-model="values.preset_group"></v-select>
            </v-col>
          </v-row>
          <!-- DATA FORMAT & SECTION FORMAT -->
          <v-row>
            <v-col cols="6">
              <v-select label="Structured Data Format" :items="dataManageFormatChoices" v-model="values.data_format" messages="Which formatting to use for data structure communication such as function calling or general data management."></v-select>
            </v-col>
            <v-col cols="6">
              <v-select label="Section Format" :items="sectionFormatChoices" v-model="values.section_format" messages="How prompt sections are formatted. Markdown uses ## headings, XML uses paired tags like <SECTION>...</SECTION>."></v-select>
            </v-col>
          </v-row>
          <!-- RESPONSE LENGTH ENFORCEMENT -->
          <v-row>
            <v-col cols="6">
              <v-select v-model="values.enforce_response_length" label="Response Length Enforcement" :items="enforceResponseLengthChoices"
                item-title="label" item-value="value" hint="Controls whether token limits and/or length instructions are sent with prompts." persistent-hint>
                <template v-slot:item="{ props, internalItem: item }">
                  <v-list-item v-bind="props" :title="item.raw.label" :subtitle="item.raw.help"></v-list-item>
                </template>
              </v-select>
              <v-alert v-if="values.enforce_response_length === 'uncapped'" color="warning" variant="text" density="compact" class="mt-1 text-body-small" icon="mdi-alert">
                Not recommended. Any generation length settings will be ignored when this is selected.
              </v-alert>
            </v-col>
            <v-col cols="6">
              <v-checkbox v-model="values.optimize_prompt_caching" color="primary" label="Optimize for Prompt Caching" hint="Place volatile context after the scene history for better prompt caching. Recommended for remote API backends. May confuse weaker models." persistent-hint></v-checkbox>
            </v-col>
          </v-row>
          <!-- DEDUPE PROMPT -->
          <v-row>
            <v-col cols="12">
              <v-checkbox v-model="values.dedupe_enabled" color="primary" label="Deduplicate Prompts" hint="Strip near-duplicate lines from rendered prompts before sending. Off by default — modern context windows make the token savings negligible and the rewrites break prompt caching. Enable only if RAG injection is producing substantial duplication and the context window is tight." persistent-hint></v-checkbox>
            </v-col>
          </v-row>
          <!-- RATE LIMIT -->
          <v-row>
            <v-col cols="12">
              <v-slider v-model="values.rate_limit" label="Rate Limit" :min="0" :max="100" :step="1" :persistent-hint="true" hint="Requests per minute. (0 = no limit)" thumb-label="always"></v-slider>
            </v-col>
          </v-row>
          <!-- AUTO RETRY -->
          <v-alert icon="mdi-refresh" density="compact" class="text-medium-emphasis" variant="text">
            Automatic retries on response issues before you are notified. (0 = notify immediately)
          </v-alert>
          <v-row>
            <v-col cols="6">
              <v-slider v-model="values.retry_empty_response" label="Empty Response" :min="0" :max="5" :step="1" :persistent-hint="true" hint="Automatic retries when the model returns an empty response." thumb-label="always"></v-slider>
            </v-col>
            <v-col cols="6">
              <v-slider v-model="values.retry_rate_limit" label="Rate Limited" :min="0" :max="5" :step="1" :persistent-hint="true" hint="Automatic retries when the API reports it is rate limited (HTTP 429), waiting progressively longer between attempts." thumb-label="always"></v-slider>
            </v-col>
          </v-row>
        </v-expansion-panel-text>
      </v-expansion-panel>

      <!-- REASONING -->
      <v-expansion-panel value="reasoning" data-setting-anchor="reasoning">
        <v-expansion-panel-title>
          <v-icon class="mr-2" color="primary" size="small">mdi-brain</v-icon> Reasoning
        </v-expansion-panel-title>
        <v-expansion-panel-text>
          <v-alert icon="mdi-brain" density="compact" class="text-medium-emphasis" variant="text">
            Configuration to deal with reasoning models.
          </v-alert>
          <v-alert density="compact" variant="tonal" color="primary" icon="mdi-tune" class="mb-2">
            <div class="d-flex align-center flex-wrap ga-2">
              <span class="text-body-small">Reasoning can also be turned off per agent action, whichever client runs it.</span>
              <v-spacer></v-spacer>
              <v-tooltip location="top" text="Open the agent action overrides">
                <template #activator="{ props }">
                  <v-btn v-bind="props" size="small" variant="tonal" color="primary" prepend-icon="mdi-tune" class="text-none"
                    data-testid="client-reasoning-overrides-door" @click="openAgentActionOverrides()">
                    Agent action overrides
                    <v-chip v-if="overrideCount > 0" size="x-small" label color="primary" variant="flat" class="ml-1">{{ overrideCount }}</v-chip>
                  </v-btn>
                </template>
              </v-tooltip>
            </div>
          </v-alert>
          <v-row>
            <v-col cols="12">
              <v-checkbox v-model="reasonEnabled" label="Enable Reasoning" hide-details :disabled="reasonLocked"></v-checkbox>
              <v-card v-if="reasonLocked" variant="outlined" color="primary" class="mt-2">
                <v-card-text class="text-body-small text-muted pa-2">
                  <div v-if="values.model && values.model !== modelName">
                    Reasoning is always enabled for the model <strong>{{ modelName }}</strong>. You have selected a different model (<strong>{{ values.model }}</strong>). Please save the client configuration and return to this screen to see if reasoning is required for the new model.
                  </div>
                  <div v-else>
                    Reasoning is always enabled for the model <strong>{{ modelName }}</strong> and cannot be disabled.
                  </div>
                </v-card-text>
              </v-card>
            </v-col>
            <v-col cols="12" v-if="reasonEnabled">
              <TokenBudgetInput v-model="values.reason_tokens" :label="meta.reason_tokens_as_allowance ? 'Extra Completion Tokens' : 'Reasoning Tokens'" :min="minReasonTokens" :persistent-hint="true" :hint="meta.reason_tokens_as_allowance ? 'Extra room in the total completion limit for reasoning and the answer. This does not set a reasoning budget; choose Reasoning Effort below.' : 'Tokens to spend on reasoning.'" />
              <v-alert v-if="!meta.reason_tokens_as_allowance" color="muted" variant="text" class="text-body-small">
                <p>The behavior of this depends on the provider and model.</p>
                <p class="mt-2">For APIs that provide a way to specify the reasoning tokens, this will be the amount of tokens to spend on reasoning.</p>
                <p class="mt-2">For APIs that do <span class="text-warning">NOT</span> provide a way to specify the reasoning tokens, this will simply add extra allowance for response tokens to ALL requests.</p>
                <p class="mt-2">
                  Talemate relies strongly on response token limit to wrangle model verbosity normally, so in the latter case this can lead to more verbose responses than wanted.
                </p>
              </v-alert>
            </v-col>
            <v-col cols="12" v-if="reasonEnabled && requiresReasoningPattern">
              <v-sheet color="transparent" class="text-body-small text-right">
                <!-- each preset sets BOTH the strip and validation patterns for that model -->
                <v-btn @click.stop="applyReasoningPreset('', '')" size="small" color="primary" variant="text">{{ 'Default' }}</v-btn>
                <v-btn @click.stop="applyReasoningPreset('.*?final<\\|message\\|>', '<\\|channel\\|>analysis')" size="small" color="primary" variant="text">{{ 'gpt-oss' }}</v-btn>
                <v-btn @click.stop="applyReasoningPreset('.*?<channel\\|>', '<\\|channel>thought')" size="small" color="primary" variant="text">{{ 'gemma-4' }}</v-btn>
                <v-btn @click.stop="applyReasoningPreset('.*?◁/think▷', '◁think▷')" size="small" color="primary" variant="text">{{ '◁think▷' }}</v-btn>
                <v-btn @click.stop="applyReasoningPreset('.*?</think>', '<think>')" size="small" color="primary" variant="text">{{ '<think>' }}</v-btn>
              </v-sheet>
              <div class="reasoning-pattern-fields">
                <div class="reasoning-pattern-default">
                  <v-chip v-if="templateInfo.reason_response_pattern_from_template && !values.reason_response_pattern"
                    size="small" label color="primary" variant="text" prepend-icon="mdi-file-cog-outline" class="mb-1">
                    Template default: {{ templateInfo.reason_response_pattern_default }}
                    <v-tooltip activator="parent" location="top" max-width="300">
                      This strip pattern is provided by the model's prompt template{{ templateInfo.template_file ? ' (' + templateInfo.template_file + ')' : '' }} and is currently in effect because you haven't set a custom value. Enter a pattern below to override it.
                    </v-tooltip>
                  </v-chip>
                </div>
                <v-text-field v-model="values.reason_response_pattern" label="Strip pattern" hint="Regular expression used to strip the thinking tokens out of the response." :placeholder="templateInfo.reason_response_pattern_default || '.*?</think>'"></v-text-field>

                <div class="reasoning-pattern-default">
                  <v-chip v-if="templateInfo.reason_validation_pattern_from_template && !values.reason_validation_pattern"
                    size="small" label color="primary" variant="text" prepend-icon="mdi-file-cog-outline" class="mb-1">
                    Template default: {{ templateInfo.reason_validation_pattern_default }}
                    <v-tooltip activator="parent" location="top" max-width="300">
                      This validation pattern is provided by the model's prompt template{{ templateInfo.template_file ? ' (' + templateInfo.template_file + ')' : '' }} and is currently in effect because you haven't set a custom value. Enter a pattern below to override it.
                    </v-tooltip>
                  </v-chip>
                </div>
                <v-text-field v-model="values.reason_validation_pattern" label="Validation pattern (reasoning start)" hint="Optional. Matches the START of the reasoning tokens. If set and not found in the response (and not prefilled), the model never reasoned and the response is returned as-is instead of failing." :placeholder="templateInfo.reason_validation_pattern_default || ''"></v-text-field>

              </div>
            </v-col>
          </v-row>
          <v-row v-if="reasonEnabled && requiresReasoningPattern">
            <v-col :cols="values.reason_failure_behavior === 'fail' ? 6 : 12">
              <v-select v-model="values.reason_failure_behavior" label="Pattern Not Found Behavior"
                :items="[
                  { title: 'Fail - raise an error', value: 'fail' },
                  { title: 'Ignore - return response as is', value: 'ignore' }
                ]"
                hint="What to do when the reasoning pattern is not found in the response." persistent-hint></v-select>
            </v-col>
            <v-col cols="6" v-if="values.reason_failure_behavior === 'fail'">
              <v-slider v-model="values.retry_missing_reasoning" label="Auto Retry" :min="0" :max="5" :step="1" :persistent-hint="true" hint="Automatic retries when the reasoning pattern is missing, before you are notified. (0 = notify immediately)" thumb-label="always"></v-slider>
            </v-col>
          </v-row>
          <v-row v-if="reasonEnabled && requiresReasoningPattern">
            <v-col cols="12">
              <v-text-field v-model="values.reason_prefill" label="Reason Prefill"></v-text-field>
              <v-alert color="muted" variant="text" class="text-body-small">
                This is mostly for base models that don't have reasoning built in, but were fine-tuned for reasoning. For example add <code class="text-primary">&lt;think&gt;</code> here to force the model to reason. Assuming <code class="text-primary">&lt;think&gt;</code> is the actual start of the thinking process, this may vary depending on the model.
              </v-alert>
            </v-col>
          </v-row>
          <!-- extra fields promoted to the reasoning section -->
          <UxField v-for="field in extraFieldsBySection['reasoning']" :key="field.name" :field="field"
            :model-value="values[field.name]" @update:model-value="(v) => setValue(field.name, v)" :app-config="config" />
        </v-expansion-panel-text>
      </v-expansion-panel>

      <!-- EXTRA FIELD GROUPS, ONE PANEL PER GROUP -->
      <v-expansion-panel v-for="group in extraFieldGroups" :key="group.name" :value="group.name">
        <v-expansion-panel-title>
          <v-icon class="mr-2" color="primary" size="small">{{ group.icon }}</v-icon> {{ group.label }}
        </v-expansion-panel-title>
        <v-expansion-panel-text>
          <v-alert v-if="group.description" color="muted" variant="text" density="compact" :icon="group.icon" class="mb-2 pre-wrap">{{ group.description.replace(/{client_type}/g, client.type) }}</v-alert>
          <UxField v-for="field in extraFieldsByGroup[group.name]" :key="field.name" :field="field"
            :model-value="values[field.name]" @update:model-value="(v) => setValue(field.name, v)" :app-config="config" />
        </v-expansion-panel-text>
      </v-expansion-panel>

      <!-- SYSTEM PROMPTS -->
      <v-expansion-panel value="system_prompts" data-setting-anchor="system_prompts">
        <v-expansion-panel-title>
          <v-icon class="mr-2" color="primary" size="small">mdi-text-box</v-icon> System Prompts
        </v-expansion-panel-title>
        <v-expansion-panel-text>
          <AppConfigPresetsSystemPrompts
            :immutable-config="client"
            :decensor-available="meta.requires_prompt_template"
            :system-prompt-defaults="config ? config.system_prompt_defaults : {}"
            @update="(updated) => client.system_prompts = updated.system_prompts"
            scope="client"
          ></AppConfigPresetsSystemPrompts>
        </v-expansion-panel-text>
      </v-expansion-panel>

    </v-expansion-panels>
  </v-form>
</template>

<script>

import { v4 as uuidv4 } from 'uuid';
import { markRaw } from 'vue';
import { conditionMet } from '@/utils/uxConditions';
import { countOverrides } from '@/utils/agentActionOverrides';
import { contextLengthWarning } from '@/constants/modelExpectations';
import AppConfigPresetsSystemPrompts from './AppConfigPresetsSystemPrompts.vue';
import ConfigWidgetUnifiedApiKey from './ConfigWidgetUnifiedApiKey.vue';
import TokenBudgetInput from './TokenBudgetInput.vue';
import ModelExpectationsPanel from './ModelExpectationsPanel.vue';
import UxField from './UxField.vue';

// Sections that exist as hardcoded panels — extra fields whose group name
// matches one of these are rendered inside that panel instead of getting a
// panel of their own.
const HARDCODED_SECTIONS = ['general', 'coercion', 'advanced', 'reasoning', 'system_prompts'];

// Editor for a single client, bound to the app settings working copy.
//
// Values are read through the `values` accessor (working copy value, falling
// back to the client type's `Meta.defaults` for keys the stored client does
// not carry) and written straight back into the passed `client` object — the
// same in-place binding the native settings pages use, so the host's dirty
// tracking (a JSON diff against its snapshot) picks edits up without any
// event plumbing. Only the rename is emitted: the client map is keyed by name
// and re-keying is the host page's business.
//
// Nothing here talks to the backend except the prompt template flows, which
// manage template files rather than configuration and stay immediate RPCs.
export default {
  name: 'ClientConfigEditor',
  components: {
    AppConfigPresetsSystemPrompts,
    ConfigWidgetUnifiedApiKey,
    TokenBudgetInput,
    ModelExpectationsPanel,
    UxField,
  },
  props: {
    // the client object inside the working app config copy
    client: Object,
    // Meta().model_dump() of the client's type (from the client_types message)
    meta: {
      type: Object,
      default: () => ({}),
    },
    // the full working app config copy — cross references (inference preset
    // groups, unified api keys, system prompt defaults)
    config: Object,
    // (value) => true | string, name uniqueness against the client map
    validateName: {
      type: Function,
      default: null,
    },
    // reduced field set for the onboarding embed
    simple: {
      type: Boolean,
      default: false,
    },
    // live client_status message for this client, when it exists — read-only
    // hints (model name, prompt template state, runtime capabilities)
    status: {
      type: Object,
      default: null,
    },
  },
  emits: ['rename'],
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'navigateToLLMTemplates', 'openAgentActionOverrides'],
  data() {
    return {
      openPanels: ['general'],
      nameDraft: this.client ? this.client.name : '',
      promptTemplates: [],
      // prompt template state applied by the template RPCs, layered over the
      // live status data — none of it belongs in the working copy
      templateState: {},
      pendingTemplateRequest: null,
      waitingForTemplateSelection: false,
      rules: {
        required: value => !!value || 'Field is required.',
      },
      rulesMaxTokenLength: [
        v => !!v || 'Context length is required',
      ],
      dataManageFormatChoices: [
        { title: 'Talemate decides', value: null },
        { title: 'JSON', value: 'json' },
        { title: 'YAML', value: 'yaml' },
      ],
      sectionFormatChoices: [
        { title: 'Talemate decides', value: null },
        { title: 'Markdown', value: 'markdown' },
        { title: 'XML', value: 'xml' },
      ],
    };
  },
  computed: {
    // Effective field access: reads fall back to the client type's defaults
    // for keys the stored client lacks (a client type may have gained fields
    // since the client was created, and a freshly added client carries only
    // what `Meta.defaults` ships), with the backend model's defaults beneath
    // those. Writes always land in the working copy.
    // Deliberately no fallback for explicit nulls — null is a meaningful
    // value for most client fields (e.g. "Talemate decides").
    values() {
      const client = this.client || {};
      const defaults = { ...(this.meta.model_defaults || {}), ...(this.meta.defaults || {}) };
      return new Proxy({}, {
        get: (_, key) => client[key] === undefined ? defaults[key] : client[key],
        set: (_, key, value) => {
          client[key] = value;
          return true;
        },
        has: (_, key) => key in client || key in defaults,
      });
    },
    typeTitle() {
      return this.meta.title || this.client?.type;
    },
    requiresAPIUrl() {
      return (this.meta.defaults || {}).api_url != null;
    },
    unifiedApiKeyPath() {
      return this.meta.unified_api_key_config_path || null;
    },
    unifiedApiKeyDescription() {
      return `This API key is stored in application settings and shared across all ${this.typeTitle} clients. You can also edit it on the API Keys page.`;
    },
    modelChoices() {
      // comes from either the live status (dynamically fetched model lists)
      // or the client type's meta
      const liveChoices = this.status?.data?.manual_model_choices;
      if (liveChoices && liveChoices.length > 0) {
        return liveChoices;
      }
      return this.meta.manual_model_choices;
    },
    modelName() {
      return this.status?.model_name || this.values.model;
    },
    contextLengthWarning() {
      return contextLengthWarning(this.values.max_token_length);
    },
    // runtime capabilities — only the live client knows these, the defaults
    // below are what a not-yet-instantiated client would report
    canBeCoerced() {
      if (this.status) {
        return this.status.data?.can_be_coerced;
      }
      return this.meta.requires_prompt_template && !this.values.reason_enabled;
    },
    requiresReasoningPattern() {
      return this.status ? !!this.status.data?.requires_reasoning_pattern : true;
    },
    reasonLocked() {
      return this.status ? !!this.status.data?.reason_locked : false;
    },
    reasonEnabled: {
      get() {
        return this.reasonLocked || this.values.reason_enabled;
      },
      set(value) {
        if (!this.reasonLocked) this.values.reason_enabled = value;
      },
    },
    overrideCount() {
      return countOverrides(this.config?.agent_actions?.overrides);
    },
    minReasonTokens() {
      return this.status?.data?.min_reason_tokens || 0;
    },
    templateInfo() {
      return { ...(this.status?.data || {}), ...this.templateState };
    },
    templateScope() {
      return JSON.stringify([
        this.client?.name,
        this.client?.type,
        !!this.values.lock_template,
        this.values.lock_template ? null : this.modelName,
        !!this.values.api_handles_prompt_template,
      ]);
    },
    promptTemplateAvailable() {
      return !!this.status
        && this.meta.requires_prompt_template
        && !!this.modelName
        && this.templateInfo.prompt_template_example !== null
        && !this.templateInfo.api_handles_prompt_template;
    },
    availablePresets() {
      const items = [{ title: 'Default', value: '' }];
      const inferenceGroups = this.config?.presets?.inference_groups;
      if (!inferenceGroups) {
        return items;
      }
      for (const [key, value] of Object.entries(inferenceGroups)) {
        items.push({ title: value.name, value: key });
      }
      items.sort((a, b) => a.title.localeCompare(b.title));
      return items;
    },
    enforceResponseLengthChoices() {
      if (this.status?.data?.field_choices?.enforce_response_length) {
        return this.status.data.field_choices.enforce_response_length;
      }
      return [
        { label: 'Uncapped', value: 'uncapped', help: 'No token limit, no length instructions' },
        { label: 'Limit tokens and send instructions', value: 'cap_tokens_and_instructions', help: 'Limits the API token budget and appends length instructions' },
        { label: 'Limit tokens', value: 'cap_tokens', help: 'Limits the API token budget without length instructions' },
        { label: 'Send instructions', value: 'instructions', help: 'Appends length instructions without limiting tokens' },
        { label: 'Adaptive', value: 'adaptive', help: 'Sends instructions only when reasoning is enabled, otherwise limits tokens and sends instructions' },
      ];
    },
    nameRules() {
      const rules = [this.rules.required];
      if (this.validateName) {
        rules.push(this.validateName);
      }
      return rules;
    },
    visibleExtraFields() {
      // extra fields whose visibility condition is met against the current
      // client values
      return Object.values(this.meta.extra_fields || {}).filter(this.extraFieldConditionMet);
    },
    generalExtraFields() {
      return this.visibleExtraFields
        .filter(field => !field.group)
        .map(this.prepareExtraField);
    },
    // A grouped extra field goes either into the hardcoded panel its group
    // names or into a panel of its own — one pass, two buckets.
    groupedExtraFields() {
      const bySection = {};
      const byGroup = {};
      const groups = {};
      for (const field of this.visibleExtraFields) {
        if (!field.group) {
          continue;
        }
        const name = field.group.name;
        const bucket = HARDCODED_SECTIONS.includes(name) ? bySection : byGroup;
        (bucket[name] || (bucket[name] = [])).push(this.prepareExtraField(field));
        if (bucket === byGroup) {
          groups[name] = field.group;
        }
      }
      return { bySection, byGroup, groups: Object.values(groups) };
    },
    extraFieldsBySection() {
      return this.groupedExtraFields.bySection;
    },
    extraFieldGroups() {
      return this.groupedExtraFields.groups;
    },
    extraFieldsByGroup() {
      return this.groupedExtraFields.byGroup;
    },
  },
  watch: {
    templateScope: {
      flush: 'sync',
      handler() {
        this.templateState = {};
        this.clearPendingTemplateRequest();
        this.waitingForTemplateSelection = false;
      },
    },
    status() {
      // A draft lock uses a different template file until Save applies it.
      if (this.pendingTemplateRequest || this.waitingForTemplateSelection
        || !!this.status?.data?.lock_template !== !!this.values.lock_template) {
        return;
      }
      this.templateState = {};
    },
    client: {
      immediate: true,
      handler(newVal, oldVal) {
        // the host adopts a fresh config after every save, which swaps the
        // object identity of the same client — only a real selection change
        // resets the local state, otherwise saving would collapse the panels
        // and drop the template state mid-edit
        if (oldVal && newVal && newVal.name === oldVal.name) {
          return;
        }
        // another client selected — drop the previous client's local state
        this.nameDraft = newVal ? newVal.name : '';
        this.templateState = {};
        this.clearPendingTemplateRequest();
        this.waitingForTemplateSelection = false;
        this.openPanels = ['general'];
      },
    },
  },
  methods: {
    prepareExtraField(field) {
      // Clone the field definition and substitute {client_type} in the
      // user-facing texts before handing it to the shared UxField renderer.
      const prepared = JSON.parse(JSON.stringify(field));
      const sub = (text) => text ? text.replace(/{client_type}/g, this.client?.type) : text;
      prepared.description = sub(prepared.description);
      if (prepared.note) {
        prepared.note.text = sub(prepared.note.text);
      }
      for (const key in prepared.note_on_value) {
        prepared.note_on_value[key].text = sub(prepared.note_on_value[key].text);
      }
      return prepared;
    },
    setValue(name, value) {
      this.client[name] = value;
    },
    extraFieldConditionMet(field) {
      // Conditions on client extra fields resolve against the client's
      // current field values (mirrors how agent settings resolve conditions
      // against action config values).
      const value = field.condition ? this.values[field.condition.attribute] : null;
      return conditionMet(field.condition, value);
    },
    commitName() {
      const name = (this.nameDraft || '').trim();
      if (!name || name === this.client.name) {
        this.nameDraft = this.client.name;
        return;
      }
      if (this.validateName && this.validateName(name) !== true) {
        return;
      }
      this.$emit('rename', name);
    },
    applyReasoningPreset(stripPattern, validationPattern) {
      this.values.reason_response_pattern = stripPattern;
      this.values.reason_validation_pattern = validationPattern;
    },
    openLLMTemplates() {
      this.navigateToLLMTemplates();
    },
    lockTemplateChanged(value) {
      this.values.lock_template = value;
      this.templateState = { ...this.templateState, template_file: null };
      this.waitingForTemplateSelection = true;
      if (!value) {
        this.determineBestTemplate();
      }
    },
    sendRequest(action, data, requestId) {
      this.getWebsocket().send(JSON.stringify({
        type: 'config',
        action: action,
        data: data,
        request_id: requestId,
      }));
    },
    requestStdTemplates() {
      this.sendRequest('request_std_llm_templates', {});
    },
    determineBestTemplate() {
      this.requestTemplate('determine_llm_template');
    },
    setPromptTemplate(templateFile) {
      this.templateState = { ...this.templateState, template_file: templateFile };
      this.requestTemplate('set_llm_template', { template_file: templateFile });
      this.$refs.promptTemplateComboBox.blur();
    },
    clearPendingTemplateRequest() {
      const pending = this.pendingTemplateRequest;
      if (pending) {
        pending.socket.removeEventListener('close', pending.onClose);
        this.pendingTemplateRequest = null;
      }
    },
    requestTemplate(action, data = {}) {
      this.clearPendingTemplateRequest();
      const socket = this.getWebsocket();
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        this.templateState = {};
        this.waitingForTemplateSelection = false;
        return;
      }
      const requestId = uuidv4();
      const onClose = () => {
        if (this.pendingTemplateRequest?.id !== requestId) return;
        this.clearPendingTemplateRequest();
        this.templateState = {};
        this.waitingForTemplateSelection = false;
      };
      this.pendingTemplateRequest = { id: requestId, scope: this.templateScope, socket: markRaw(socket), onClose };
      socket.addEventListener('close', onClose);
      this.sendRequest(action, {
        ...data,
        model: this.modelName,
        client_name: (this.values.lock_template ? this.client.name : null),
      }, requestId);
    },
    handleMessage(message) {
      if (message.type !== 'config') {
        return;
      }
      if (message.action === 'std_llm_templates') {
        this.promptTemplates = message.data.templates;
        return;
      }
      if (!this.pendingTemplateRequest
        || message.request_id !== this.pendingTemplateRequest.id
        || this.pendingTemplateRequest.scope !== this.templateScope
        || this.pendingTemplateRequest.socket !== this.getWebsocket()
        || this.pendingTemplateRequest.socket.readyState !== WebSocket.OPEN) {
        return;
      }
      if ((message.action === 'determine_llm_template_complete' && !message.data.template)
        || (message.action === 'operation_done' && message.error)) {
        this.clearPendingTemplateRequest();
        this.templateState = {};
        this.waitingForTemplateSelection = false;
        return;
      }
      if (message.action === 'set_llm_template_complete') {
        const state = {
          has_prompt_template: message.data.has_prompt_template,
          prompt_template_example: message.data.prompt_template_example,
          template_file: message.data.template_file,
        };
        for (const key of [
          'reason_response_pattern_default',
          'reason_validation_pattern_default',
          'reason_response_pattern_from_template',
          'reason_validation_pattern_from_template',
        ]) {
          if (message.data[key] !== undefined) {
            state[key] = message.data[key];
          }
        }
        this.templateState = { ...this.templateState, ...state };
        this.clearPendingTemplateRequest();
        this.waitingForTemplateSelection = false;
      }
    },
  },
  created() {
    this.registerMessageHandler(this.handleMessage);
    this.requestStdTemplates();
  },
  unmounted() {
    this.clearPendingTemplateRequest();
    this.unregisterMessageHandler(this.handleMessage);
  },
}
</script>

<style scoped>
.reasoning-pattern-fields {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  column-gap: 24px;
}
.reasoning-pattern-default:nth-child(3) {
  grid-column: 2;
  grid-row: 1;
}
.reasoning-pattern-fields > :nth-child(2),
.reasoning-pattern-fields > :nth-child(4) {
  grid-row: 2;
  min-width: 0;
}
.reasoning-pattern-default {
  min-width: 0;
}
@media (max-width: 959px) {
  .reasoning-pattern-fields {
    display: flex;
    flex-direction: column;
  }
  .reasoning-pattern-fields > :nth-child(2) {
    margin-bottom: 12px;
  }
}

.prompt-template-preview {
  white-space: pre-wrap;
  font-family: monospace;
  font-size: 0.8rem;
}

.pre-wrap {
  white-space: pre-wrap;
}
</style>
