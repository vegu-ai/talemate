<template>
    <v-list-item density="compact" @click="$emit('click', prompt)">
        <v-list-item-title class="text-caption">
            <v-row>
                <v-col cols="2" class="text-info">#{{ prompt.num }}</v-col>
                <v-col cols="10" class="text-right">
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
                        {{ prompt.prompt_tokens || 0 }}
                        <v-icon size="14" class="ml-1">mdi-arrow-down-bold</v-icon>
                    </v-chip>
                    <v-chip
                        size="x-small"
                        class="mr-1"
                        color="secondary"
                        variant="text"
                        label
                    >
                        {{ prompt.response_tokens || 0 }}
                        <v-icon size="14" class="ml-1">mdi-arrow-up-bold</v-icon>
                    </v-chip>
                    <v-chip
                        size="x-small"
                        variant="text"
                        label
                        color="grey-darken-1"
                    >
                        {{ prompt.time || 0 }}s
                        <v-icon size="14" class="ml-1">mdi-clock</v-icon>
                    </v-chip>
                </v-col>
            </v-row>
        </v-list-item-title>
        <v-list-item-subtitle class="text-caption">
            <v-chip
                v-if="prompt.agent_name"
                size="x-small"
                color="grey-lighten-1"
                variant="text"
            >
                {{ prompt.agent_name }}
            </v-chip>
            <v-chip
                v-if="prompt.agent_action"
                size="x-small"
                color="grey"
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
export default {
    name: 'PromptLogItem',
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
