<template>
    <div>
        <div class="d-flex flex-wrap mb-1">
            <v-btn
                v-for="icon in curatedIcons"
                :key="icon"
                :icon="icon"
                size="small"
                density="comfortable"
                class="ma-1"
                :variant="icon === modelValue ? 'tonal' : 'text'"
                :color="icon === modelValue ? 'primary' : 'muted'"
                @click="select(icon)"
            ></v-btn>
        </div>

        <v-text-field
            v-model="iconName"
            label="Icon"
            placeholder="mdi-sword-cross"
            density="compact"
            hide-details="auto"
            :rules="rules"
            :error-messages="errorMessages"
        >
            <template v-slot:append-inner>
                <v-icon v-if="valid" :icon="iconName" color="primary"></v-icon>
            </template>
        </v-text-field>

        <div class="text-body-small mt-1">
            <a :href="mdiListingUrl" target="_blank" rel="noopener" class="text-muted">Browse all Material Design Icons</a>
        </div>
    </div>
</template>

<script>
import { CURATED_ICONS, MDI_LISTING_URL, isValidIconName } from '@/utils/sceneToolShortcuts';

// The webfont ships no list of its names, so the only way to tell a real icon
// from a typo is to render the class and see whether the ::before rule that
// carries the glyph exists at all.
function glyphRenders(name) {
    const probe = document.createElement('span');
    probe.className = `mdi ${name}`;
    probe.style.position = 'absolute';
    probe.style.visibility = 'hidden';
    document.body.appendChild(probe);
    let content = 'none';
    try {
        content = window.getComputedStyle(probe, '::before').content;
    } finally {
        probe.remove();
    }
    return !!content && content !== 'none' && content !== 'normal' && content !== '""';
}

export default {
    name: 'IconPicker',
    props: {
        modelValue: {
            type: String,
            default: '',
        },
        // rules of the surrounding form the icon field takes part in — the
        // picker's own complaints ride on `error-messages` instead
        rules: {
            type: Array,
            default: () => [],
        },
    },
    emits: ['update:modelValue', 'update:valid'],
    data() {
        return {
            curatedIcons: CURATED_ICONS,
            mdiListingUrl: MDI_LISTING_URL,
            renders: false,
        }
    },
    computed: {
        iconName: {
            get() {
                return this.modelValue;
            },
            set(value) {
                this.$emit('update:modelValue', (value || '').trim());
            },
        },
        valid() {
            return isValidIconName(this.modelValue) && this.renders;
        },
        errorMessages() {
            if (!this.modelValue || this.valid) {
                return [];
            }
            if (!isValidIconName(this.modelValue)) {
                return ['Icon names look like mdi-sword-cross'];
            }
            return ['No such icon in the icon set'];
        },
    },
    watch: {
        modelValue: {
            immediate: true,
            handler() {
                this.check();
            },
        },
        valid: {
            immediate: true,
            handler(value) {
                this.$emit('update:valid', value);
            },
        },
    },
    methods: {
        check() {
            this.renders = isValidIconName(this.modelValue) && glyphRenders(this.modelValue);
        },
        select(icon) {
            this.$emit('update:modelValue', icon);
        },
    },
}
</script>
