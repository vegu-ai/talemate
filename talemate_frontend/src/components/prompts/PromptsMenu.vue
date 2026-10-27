<template>
    <v-list-subheader class="ml-2">
        <v-icon color="primary" class="mr-1">mdi-history</v-icon>
        Recent
    </v-list-subheader>
    <v-tabs :model-value="activeTab" @update:model-value="$emit('update:activeTab', $event)" density="compact" grow color="primary">
        <v-tab value="prompts" aria-label="Prompts" min-width="0">
            <v-icon>mdi-message-text-outline</v-icon>
            <v-tooltip activator="parent" location="bottom">Prompts</v-tooltip>
        </v-tab>
        <v-tab value="decisions" aria-label="Decisions" min-width="0">
            <v-icon>mdi-scale-balance</v-icon>
            <v-tooltip activator="parent" location="bottom">Decisions</v-tooltip>
        </v-tab>
        <v-tab value="templates" aria-label="Templates" min-width="0">
            <v-icon>mdi-file-document-outline</v-icon>
            <v-tooltip activator="parent" location="bottom">Templates</v-tooltip>
        </v-tab>
    </v-tabs>

    <v-tabs-window :model-value="activeTab">
        <!-- Recent Prompts Tab -->
        <v-tabs-window-item value="prompts">
            <v-list density="compact" slim>
                <v-card variant="text" class="mb-2">
                    <v-card-text class="text-body-small text-muted pa-2">
                        Recent prompts sent to the LLM. Click to view prompt details.
                    </v-card-text>
                </v-card>
                <v-btn
                    block
                    prepend-icon="mdi-close"
                    variant="text"
                    color="error"
                    @click="clearPrompts"
                >Clear<v-tooltip activator="parent">Clear finished requests; keep active requests.</v-tooltip></v-btn>

                <PromptLogItem
                    v-for="prompt in prompts"
                    :key="prompt.request_id"
                    :prompt="prompt"
                    :show-client="true"
                    @click="openPrompt(prompt)"
                />

                <v-list-item v-if="prompts.length === 0">
                    <v-list-item-subtitle class="text-body-small">No recent prompts</v-list-item-subtitle>
                </v-list-item>
            </v-list>
        </v-tabs-window-item>

        <!-- Recent Decisions Tab -->
        <v-tabs-window-item value="decisions">
            <v-list density="compact" slim>
                <DecisionLogView />
            </v-list>
        </v-tabs-window-item>

        <!-- Recent Templates Tab -->
        <v-tabs-window-item value="templates">
            <v-list density="compact" slim>
                <v-card variant="text" class="mb-2">
                    <v-card-text class="text-body-small text-muted pa-2">
                        Templates that recently generated prompts to the LLM. Click to navigate to the template source for editing.
                        <v-divider class="my-2"></v-divider>
                        Default templates are read-only. To override, create a copy in the <strong>user</strong> group or a custom group.
                    </v-card-text>
                </v-card>

                <v-list-item
                    v-for="template in recentTemplates"
                    :key="template.uid"
                    @click="navigateToTemplate(template)"
                >
                    <v-list-item-title class="text-body-small">{{ template.uid }}</v-list-item-title>
                    <v-list-item-subtitle>
                        <v-chip size="x-small" label variant="tonal" :color="getSourceColor(template.source_group)">{{ template.source_group }}</v-chip>
                    </v-list-item-subtitle>
                </v-list-item>

                <v-list-item v-if="recentTemplates.length === 0">
                    <v-list-item-subtitle class="text-body-small">No recent templates</v-list-item-subtitle>
                </v-list-item>
            </v-list>
        </v-tabs-window-item>
    </v-tabs-window>
</template>

<script>
import PromptLogItem from './PromptLogItem.vue';
import DecisionLogView from '../decisions/DecisionLogView.vue';

export default {
    name: "PromptsMenu",
    components: {
        PromptLogItem,
        DecisionLogView,
    },
    props: {
        prompts: {
            type: Array,
            default: () => [],
        },
        recentTemplates: {
            type: Array,
            default: () => [],
        },
        activeTab: {
            type: String,
            default: 'prompts',
        },
    },
    emits: ['navigate-template', 'open-prompt', 'clear-prompts', 'update:activeTab'],
    methods: {
        navigateToTemplate(template) {
            this.$emit('navigate-template', template);
        },
        openPrompt(prompt) {
            this.$emit('open-prompt', prompt);
        },
        clearPrompts() {
            this.$emit('clear-prompts');
        },
        getSourceColor(sourceGroup) {
            switch (sourceGroup) {
                case 'scene':
                    return 'warning';
                case 'user':
                    return 'success';
                case 'default':
                    return 'muted';
                default:
                    return 'primary';
            }
        }
    },
}
</script>
