<template>
    <v-list-subheader color="grey" class="ml-2">
        <v-icon color="primary" class="mr-1">mdi-history</v-icon>
        Recent
    </v-list-subheader>
    <v-tabs v-model="activeTab" density="compact" grow color="primary">
        <v-tab value="prompts">
            <v-icon class="mr-1">mdi-message-text-outline</v-icon>
            Prompts
        </v-tab>
        <v-tab value="templates">
            <v-icon class="mr-1">mdi-file-document-outline</v-icon>
            Templates
        </v-tab>
    </v-tabs>

    <v-tabs-window v-model="activeTab">
        <!-- Recent Prompts Tab -->
        <v-tabs-window-item value="prompts">
            <v-list density="compact" slim>
                <v-card variant="text" class="mb-2">
                    <v-card-text class="text-caption text-muted pa-2">
                        Recent prompts sent to the LLM. Click to view prompt details.
                    </v-card-text>
                </v-card>
                <v-btn
                    block
                    prepend-icon="mdi-close"
                    variant="text"
                    color="error"
                    @click="clearPrompts"
                >Clear</v-btn>

                <PromptLogItem
                    v-for="(prompt, index) in prompts"
                    :key="index"
                    :prompt="prompt"
                    :show-client="true"
                    @click="openPrompt(prompt)"
                />

                <v-list-item v-if="prompts.length === 0">
                    <v-list-item-subtitle class="text-caption">No recent prompts</v-list-item-subtitle>
                </v-list-item>
            </v-list>
        </v-tabs-window-item>

        <!-- Recent Templates Tab -->
        <v-tabs-window-item value="templates">
            <v-list density="compact" slim>
                <v-card variant="text" class="mb-2">
                    <v-card-text class="text-caption text-muted pa-2">
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
                    <v-list-item-title class="text-caption">{{ template.uid }}</v-list-item-title>
                    <v-list-item-subtitle>
                        <v-chip size="x-small" label variant="tonal" :color="getSourceColor(template.source_group)">{{ template.source_group }}</v-chip>
                    </v-list-item-subtitle>
                </v-list-item>

                <v-list-item v-if="recentTemplates.length === 0">
                    <v-list-item-subtitle class="text-caption">No recent templates</v-list-item-subtitle>
                </v-list-item>
            </v-list>
        </v-tabs-window-item>
    </v-tabs-window>
</template>

<script>
import PromptLogItem from './PromptLogItem.vue';

export default {
    name: "PromptsMenu",
    components: {
        PromptLogItem,
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
    },
    data() {
        return {
            activeTab: 'prompts',
        }
    },
    emits: ['navigate-template', 'open-prompt', 'clear-prompts'],
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
                    return 'grey';
                default:
                    return 'primary';
            }
        }
    },
}
</script>
