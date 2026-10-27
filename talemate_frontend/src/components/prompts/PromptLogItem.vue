<template>
    <v-list-item density="compact" :data-request-id="prompt.request_id" @click="$emit('click', prompt)">
        <v-list-item-title class="text-body-small">
            <div class="d-flex align-center flex-wrap ga-1">
                <span class="text-info">#{{ prompt.num }}</span>
                <PromptStatus :status="prompt.status" />
                <div class="d-flex align-center flex-nowrap ml-auto">
                    <v-chip
                        v-if="prompt.prefix_cache_ratio != null"
                        size="x-small"
                        class="mr-1"
                        variant="text"
                        label
                        :color="prompt.prefix_cache_ratio >= 0.3 ? 'success' : 'error'"
                    >
                        {{ Math.round(prompt.prefix_cache_ratio * 100) }}%
                        <v-icon size="14" class="ml-1">mdi-cached</v-icon>
                    </v-chip>
                    <v-chip
                        size="x-small"
                        class="mr-1"
                        color="primary"
                        variant="text"
                        label
                    >
                        {{ promptMetric(prompt.prompt_tokens, prompt.status) }}
                        <v-icon size="14" class="ml-1">mdi-arrow-down-bold</v-icon>
                    </v-chip>
                    <v-chip
                        size="x-small"
                        class="mr-1"
                        color="secondary"
                        variant="text"
                        label
                    >
                        {{ promptMetric(prompt.response_tokens, prompt.status) }}
                        <v-icon size="14" class="ml-1">mdi-arrow-up-bold</v-icon>
                    </v-chip>
                    <v-chip
                        size="x-small"
                        variant="text"
                        label
                        color="muted"
                    >
                        {{ promptMetric(prompt.time == null ? null : Math.floor(prompt.time), prompt.status, 's') }}
                        <v-icon size="14" class="ml-1">mdi-clock</v-icon>
                    </v-chip>
                </div>
            </div>
        </v-list-item-title>
        <v-list-item-subtitle class="text-body-small">
            <v-chip
                v-if="prompt.agent_name"
                size="x-small"
                color="mutedheader"
                variant="text"
            >
                {{ prompt.agent_name }}
            </v-chip>
            <v-chip
                v-if="prompt.agent_action"
                size="x-small"
                color="muted"
                variant="text"
            >
                {{ prompt.agent_action }}
            </v-chip>
            <v-chip
                v-if="showClient && prompt.client_name"
                size="x-small"
                color="info"
                variant="text"
            >
                {{ prompt.client_name }}
            </v-chip>
            <v-chip
                v-if="showTemplateUid && prompt.template_uid"
                size="x-small"
                color="warning"
                variant="text"
            >
                {{ prompt.template_uid }}
            </v-chip>
        </v-list-item-subtitle>
        <v-divider v-if="showDivider" class="mt-1"></v-divider>
    </v-list-item>
</template>

<script>
import PromptStatus from './PromptStatus.vue';
import { promptMetric } from '@/utils/promptLog';

export default {
    name: 'PromptLogItem',
    components: { PromptStatus },
    methods: { promptMetric },
    props: {
        prompt: {
            type: Object,
            required: true,
        },
        showClient: {
            type: Boolean,
            default: false,
        },
        showTemplateUid: {
            type: Boolean,
            default: false,
        },
        showDivider: {
            type: Boolean,
            default: true,
        },
    },
    emits: ['click'],
}
</script>
