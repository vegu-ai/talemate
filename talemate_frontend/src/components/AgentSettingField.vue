<template>
  <!-- text -->
  <v-text-field
    v-if="actionConfig.type === 'text' && actionConfig.choices === null"
    :model-value="modelValue"
    @update:modelValue="onValue"
    @keyup="$emit('change')"
    @blur="$emit('change', actionConfig.save_on_change)"
    :readonly="readonly"
    :label="actionConfig.label"
    :hint="actionConfig.description"
    density="compact"
    class="mt-3"
  >
    <template v-if="$slots.prepend" v-slot:prepend><slot name="prepend" /></template>
  </v-text-field>

  <!-- password -->
  <v-text-field
    v-else-if="actionConfig.type === 'password'"
    type="password"
    :model-value="modelValue"
    @update:modelValue="onValue"
    @keyup="$emit('change')"
    @blur="$emit('change', actionConfig.save_on_change)"
    :readonly="readonly"
    :label="actionConfig.label"
    :hint="actionConfig.description"
    density="compact"
    class="mt-3"
  >
    <template v-if="$slots.prepend" v-slot:prepend><slot name="prepend" /></template>
  </v-text-field>

  <!-- blob -->
  <v-textarea
    v-else-if="actionConfig.type === 'blob'"
    :model-value="modelValue"
    @update:modelValue="onValue"
    @keyup="$emit('change')"
    :readonly="readonly"
    :label="actionConfig.label"
    :hint="actionConfig.description"
    density="compact"
    rows="5"
    class="mt-3"
  >
    <template v-if="$slots.prepend" v-slot:prepend><slot name="prepend" /></template>
  </v-textarea>

  <!-- autocomplete -->
  <v-autocomplete
    v-else-if="actionConfig.type === 'autocomplete' && actionConfig.choices !== null"
    :model-value="modelValue"
    @update:modelValue="onValueAndChange"
    :items="actionConfig.choices"
    :readonly="readonly"
    :label="actionConfig.label"
    :hint="actionConfig.description"
    item-title="label"
    item-value="value"
    density="compact"
    class="mt-3"
  >
    <template v-if="$slots.prepend" v-slot:prepend><slot name="prepend" /></template>
  </v-autocomplete>

  <!-- wstemplate (world-state template selector) -->
  <v-autocomplete
    v-else-if="actionConfig.type === 'wstemplate'"
    :model-value="modelValue"
    @update:modelValue="onValueAndCommit"
    :items="wstemplateChoices"
    :readonly="readonly"
    :label="actionConfig.label"
    :hint="actionConfig.description"
    item-title="label"
    item-value="value"
    density="compact"
    class="mt-3"
  >
    <template v-slot:item="{ props: itemProps, item }">
      <v-list-item v-bind="itemProps" :title="item.raw.label" :subtitle="item.raw.subtitle"></v-list-item>
    </template>
    <template v-if="$slots.prepend" v-slot:prepend><slot name="prepend" /></template>
  </v-autocomplete>

  <!-- select (text + choices) -->
  <v-select
    v-else-if="actionConfig.type === 'text' && actionConfig.choices !== null"
    :model-value="modelValue"
    @update:modelValue="onValueAndCommit"
    :items="actionConfig.choices"
    :readonly="readonly"
    :label="actionConfig.label"
    :hint="actionConfig.description"
    item-title="label"
    item-value="value"
    :menu-props="{ maxHeight: 480 }"
    density="compact"
    class="mt-3"
  >
    <template v-if="$slots.prepend" v-slot:prepend><slot name="prepend" /></template>
  </v-select>

  <!-- flags (multi-select chips) -->
  <v-select
    v-else-if="actionConfig.type === 'flags'"
    :model-value="modelValue"
    @update:modelValue="onValueAndChange"
    :items="actionConfig.choices"
    :readonly="readonly"
    :label="actionConfig.label"
    :hint="actionConfig.description"
    item-title="label"
    item-subtitle="help"
    item-value="value"
    multiple
    chips
    density="compact"
    class="mt-3"
  >
    <template v-if="$slots.prepend" v-slot:prepend><slot name="prepend" /></template>
  </v-select>

  <!-- number (graduated slider) — GraduatedSlider doesn't forward slots, so
       we wrap it externally when a prepend is provided. See the v-slider
       branch below for the rationale on align-start. -->
  <div
    v-else-if="actionConfig.type === 'number' && actionConfig.graduations"
    :class="$slots.prepend ? 'd-flex align-start mt-3' : 'mt-3'"
  >
    <div v-if="$slots.prepend" class="agent-setting-field__outer-prepend">
      <slot name="prepend" />
    </div>
    <GraduatedSlider
      :model-value="modelValue"
      @update:modelValue="onValueAndChange"
      :readonly="readonly"
      :label="actionConfig.label"
      :hint="actionConfig.description"
      :min="actionConfig.min"
      :max="actionConfig.max"
      :graduations="actionConfig.graduations"
      density="compact"
      color="primary"
      thumb-label="always"
      class="flex-grow-1"
    />
  </div>

  <!-- number (slider) — v-slider's native prepend slot renders after the
       label rather than at the far left, so we wrap externally to match
       the prepend placement used by every other widget. align-start aligns
       the toggle with the slider's label row (which sits at the top of the
       slider) rather than with the vertical center of the slider track. -->
  <div
    v-else-if="actionConfig.type === 'number'"
    :class="$slots.prepend ? 'd-flex align-start mt-3' : 'mt-3'"
  >
    <div v-if="$slots.prepend" class="agent-setting-field__outer-prepend">
      <slot name="prepend" />
    </div>
    <v-slider
      :model-value="modelValue"
      @update:modelValue="onValueAndChange"
      :readonly="readonly"
      :label="actionConfig.label"
      :hint="actionConfig.description"
      :min="actionConfig.min"
      :max="actionConfig.max"
      :step="actionConfig.step || 1"
      density="compact"
      color="primary"
      thumb-label="always"
      class="flex-grow-1"
    />
  </div>

  <!-- boolean -->
  <v-checkbox
    v-else-if="actionConfig.type === 'bool'"
    :model-value="modelValue"
    @update:modelValue="onValueAndChange"
    :disabled="readonly"
    :label="actionConfig.label"
    :messages="actionConfig.description"
    density="compact"
    color="primary"
    class="mt-3"
  >
    <template v-if="$slots.prepend" v-slot:prepend><slot name="prepend" /></template>
    <template v-slot:message="{ message }">
      <span class="text-caption text-grey">{{ message }}</span>
      <span v-if="actionConfig.expensive" class="text-warning mt-2 text-caption">
        <v-icon size="x-small">mdi-alert-circle-outline</v-icon>
        Potential for many additional prompts.
      </span>
    </template>
  </v-checkbox>

  <!-- vector2 (numeric pair, optional choice presets) -->
  <v-row v-else-if="actionConfig.type === 'vector2'" class="mt-3">
    <v-col cols="12" class="d-flex align-center">
      <slot v-if="$slots.prepend" name="prepend" />
      <div class="text-caption text-muted text-uppercase">{{ actionConfig.label }}</div>
    </v-col>
    <v-col :cols="actionConfig.choices ? 5 : 6">
      <v-number-input
        :model-value="modelValue?.[0]"
        @update:modelValue="(v) => onVector2Update(0, v)"
        :readonly="readonly"
        hide-details
        type="number"
        density="compact"
      ></v-number-input>
    </v-col>
    <v-col :cols="actionConfig.choices ? 5 : 6">
      <v-number-input
        :model-value="modelValue?.[1]"
        @update:modelValue="(v) => onVector2Update(1, v)"
        :readonly="readonly"
        hide-details
        type="number"
        density="compact"
      ></v-number-input>
    </v-col>
    <v-col cols="2" v-if="actionConfig.choices" class="d-flex align-center justify-center">
      <v-menu location="bottom end" :disabled="readonly">
        <template v-slot:activator="{ props: activatorProps }">
          <v-chip v-bind="activatorProps" size="small" variant="tonal" color="primary" class="px-2">
            <v-icon icon="mdi-menu-down"></v-icon>
          </v-chip>
        </template>
        <v-list density="compact">
          <v-list-item
            v-for="(choice, i) in actionConfig.choices"
            :key="i"
            :value="i"
            @click="onValueAndChange([...choice.value])"
          >
            <v-list-item-title>{{ choice.label }}</v-list-item-title>
          </v-list-item>
        </v-list>
      </v-menu>
    </v-col>
  </v-row>

  <!-- table — custom widget; emits the full values array on save. -->
  <div v-else-if="actionConfig.type === 'table'" :class="$slots.prepend ? 'd-flex align-start' : ''">
    <div v-if="$slots.prepend" class="agent-setting-field__outer-prepend mt-3">
      <slot name="prepend" />
    </div>
    <ConfigWidgetTable
      class="flex-grow-1"
      :columns="actionConfig.columns"
      :default_values="modelValue"
      :label="actionConfig.label"
      :description="actionConfig.description"
      @save="onValueAndChange"
    />
  </div>

  <!-- weights — custom widget. -->
  <div v-else-if="actionConfig.type === 'weights'" :class="$slots.prepend ? 'd-flex align-start' : ''">
    <div v-if="$slots.prepend" class="agent-setting-field__outer-prepend mt-3">
      <slot name="prepend" />
    </div>
    <ConfigWidgetWeights
      class="flex-grow-1"
      :model-value="modelValue"
      @update:modelValue="onValueAndChange"
      :choices="actionConfig.choices"
      :label="actionConfig.label"
      :description="actionConfig.description"
      :step="actionConfig.step || 0.05"
    />
  </div>

  <!-- unified_api_key — bound to global app config; no per-field value. -->
  <ConfigWidgetUnifiedApiKey
    v-else-if="actionConfig.type === 'unified_api_key'"
    :config-path="actionConfig.value"
    :title="actionConfig.label"
    :app-config="appConfig"
    class="mt-3"
  />

  <!-- fallback -->
  <v-alert v-else density="compact" variant="text" color="muted" class="mt-3">
    <span class="text-caption">Widget type "{{ actionConfig.type }}" ({{ actionConfig.label }}) is not supported.</span>
  </v-alert>

  <!-- Field notes — `note_on_value` matches against the current modelValue,
       which in scene mode is the effective value (override when active). -->
  <template v-if="actionConfig.note != null">
    <v-alert variant="outlined" density="compact" :color="actionConfig.note.color || 'muted'" :icon="actionConfig.note.icon">
      <div class="text-caption text-mutedheader">{{ actionConfig.note.title || actionConfig.label }}</div>
      <span class="text-muted text-caption">{{ actionConfig.note.text }}</span>
    </v-alert>
  </template>
  <template v-else-if="actionConfig.note_on_value != null">
    <template v-for="(note, noteKey) in actionConfig.note_on_value" :key="noteKey">
      <v-alert v-if="modelValue == noteKey || String(modelValue) == noteKey" variant="outlined" density="compact" :color="note.color || 'muted'" class="my-2" :icon="note.icon">
        <span class="text-caption text-uppercase mr-2">
          {{ noteKey.toLowerCase() === 'true' ? 'ENABLED' : noteKey.replace(/_/g, ' ') }}
        </span>
        <span class="text-muted text-caption">{{ note.text }}</span>
      </v-alert>
    </template>
  </template>
</template>

<script>
import { getProperty } from 'dot-prop';
import ConfigWidgetTable from './ConfigWidgetTable.vue';
import ConfigWidgetUnifiedApiKey from './ConfigWidgetUnifiedApiKey.vue';
import ConfigWidgetWeights from './ConfigWidgetWeights.vue';
import GraduatedSlider from './GraduatedSlider.vue';

// Renders a single AgentActionConfig field across all supported widget
// types. Shared by [[AgentGlobalSettings.vue]] and [[AgentSceneSettings.vue]];
// the latter passes a `prepend` slot for the override toggle and `readonly`
// when the override is inactive.
export default {
  components: { ConfigWidgetTable, ConfigWidgetUnifiedApiKey, ConfigWidgetWeights, GraduatedSlider },
  props: {
    actionConfig: { type: Object, required: true },
    modelValue: { type: null, default: null },
    readonly: { type: Boolean, default: false },
    // Required for wstemplate widgets.
    templates: { type: Object, default: null },
    // Required for unified_api_key widgets.
    appConfig: { type: Object, default: null },
  },
  emits: ['update:modelValue', 'change'],
  computed: {
    wstemplateChoices() {
      const bucket = this.templates?.by_type?.[this.actionConfig?.wstemplate_type];
      if (!bucket) return [];
      const groupNameByUid = Object.fromEntries(
        (this.templates?.managed?.groups ?? [])
          .filter(Boolean)
          .map(g => [g.uid, g.name || g.uid])
      );
      const filter = this.actionConfig?.wstemplate_filter;
      const hasFilter = filter && typeof filter === 'object' && Object.keys(filter).length > 0;
      const items = [];
      for (const [uid, template] of Object.entries(bucket)) {
        if (hasFilter) {
          let match = true;
          for (const key in filter) {
            const expected = filter[key];
            const actual = getProperty(template, key);
            if (Array.isArray(expected)) {
              if (!expected.some(v => v == actual)) { match = false; break; }
            } else if (expected != actual) {
              match = false; break;
            }
          }
          if (!match) continue;
        }
        const subtitle = template?.group ? (groupNameByUid[template.group] || template.group) : undefined;
        items.push({ label: template?.name || uid, value: uid, subtitle });
      }
      return items;
    },
  },
  methods: {
    onValue(value) {
      this.$emit('update:modelValue', value);
    },
    onValueAndChange(value) {
      this.$emit('update:modelValue', value);
      this.$emit('change');
    },
    onValueAndCommit(value) {
      this.$emit('update:modelValue', value);
      this.$emit('change', this.actionConfig.save_on_change);
    },
    onVector2Update(index, value) {
      const next = [...(this.modelValue || [0, 0])];
      next[index] = value;
      this.onValueAndChange(next);
    },
  },
};
</script>

<style scoped>
/* Vuetify applies pointer-events: none on disabled/readonly v-inputs, which
   also blocks the override toggle in the prepend slot. Re-enable so the
   toggle stays clickable. */
:deep(.v-input--disabled) .v-input__prepend,
:deep(.v-input--readonly) .v-input__prepend {
  pointer-events: auto;
  opacity: 1;
}

/* External prepend wrapper for widgets that don't expose a Vuetify-native
   prepend slot (GraduatedSlider, v-slider, ConfigWidget*). Matches the
   inline-end padding (8px) that Vuetify's native .v-input__prepend uses so
   the toggle aligns horizontally with prepend toggles on neighbouring
   widgets. The small padding-top nudges the toggle icon down to align
   with the host widget's label baseline (used with align-start parent). */
.agent-setting-field__outer-prepend {
  display: flex;
  align-items: center;
  padding-inline-end: 8px;
  padding-top: 6px;
}
</style>
