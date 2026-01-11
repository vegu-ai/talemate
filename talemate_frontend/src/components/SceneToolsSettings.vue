<template>
    <v-menu>
        <template v-slot:activator="{ props }">
            <v-chip
                size="x-small"
                v-bind="props"
                color="muted"
                variant="tonal"
                class="ma-1"
                :disabled="appBusy || !appReady"
            >
                <v-icon class="mr-1">mdi-cog</v-icon>
                Settings
            </v-chip>
        </template>
        <v-list density="compact">
            <template v-for="(group, index) in settingsGroups" :key="index">
                <v-list-subheader v-if="group.subheader">{{ group.subheader }}</v-list-subheader>
                <v-list-item
                    v-for="(item, itemIndex) in group.items"
                    :key="itemIndex"
                    @click="item.action"
                    density="compact"
                >
                    <template v-slot:prepend>
                        <v-icon :icon="item.icon"></v-icon>
                    </template>
                    <v-list-item-title>{{ item.title }}</v-list-item-title>
                    <v-list-item-subtitle v-if="item.subtitle">{{ item.subtitle }}</v-list-item-subtitle>
                </v-list-item>
            </template>
        </v-list>
    </v-menu>
</template>

<script>
export default {
    name: 'SceneToolsSettings',
    props: {
        appBusy: {
            type: Boolean,
            default: false
        },
        appReady: {
            type: Boolean,
            default: true
        }
    },
    inject: [
        'openAppConfig',
        'openAgentSettings',
    ],
    computed: {
        settingsGroups() {
            return [
                {
                    subheader: 'Application',
                    items: [
                        {
                            title: 'Game Settings',
                            subtitle: 'Auto-save, auto-progress, and display options',
                            icon: 'mdi-gamepad-square',
                            action: () => this.openAppConfig('game', 'general')
                        },
                        {
                            title: 'Appearance',
                            subtitle: 'Colors, text styles, and other visual preferences',
                            icon: 'mdi-palette',
                            action: () => this.openAppConfig('appearance')
                        }
                    ]
                },
                {
                    subheader: 'Agents',
                    items: [
                        {
                            title: 'Conversation / Actor',
                            subtitle: 'Format, length, and other generation settings',
                            icon: 'mdi-forum',
                            action: () => this.openAgentSettings('conversation', 'generation_override')
                        },
                        {
                            title: 'Narrator',
                            subtitle: 'Generation settings, instructions, and auto-narration',
                            icon: 'mdi-book-open-variant',
                            action: () => this.openAgentSettings('narrator', null)
                        },
                        {
                            title: 'Creator',
                            subtitle: 'Autocomplete settings',
                            icon: 'mdi-creation',
                            action: () => this.openAgentSettings('creator', 'autocomplete')
                        },
                        {
                            title: 'Director',
                            subtitle: 'Direction settings and modes',
                            icon: 'mdi-movie-open',
                            action: () => this.openAgentSettings('director', 'scene_direction')
                        },
                        {
                            title: 'Visualizer',
                            subtitle: 'Backends and auto-generation',
                            icon: 'mdi-image',
                            action: () => this.openAgentSettings('visual', '_config')
                        },
                        {
                            title: 'Text to Speech',
                            subtitle: 'Voice generation and auto-speech',
                            icon: 'mdi-microphone',
                            action: () => this.openAgentSettings('tts', 'text_to_speech')
                        },
                        {
                            title: 'World State',
                            subtitle: 'World state updates and reinforcement',
                            icon: 'mdi-earth',
                            action: () => this.openAgentSettings('world_state', 'update_world_state')
                        },
                        {
                            title: 'Editor',
                            subtitle: 'Automatic revisions and post-processing of generated text',
                            icon: 'mdi-pencil',
                            action: () => this.openAgentSettings('editor', 'revision')
                        },
                        {
                            title: 'Summarizer',
                            subtitle: 'Auto-summarization and context management',
                            icon: 'mdi-text-short',
                            action: () => this.openAgentSettings('summarizer', 'archive')
                        },
                        {
                            title: 'Memory',
                            subtitle: 'Embeddings and vector database settings',
                            icon: 'mdi-memory',
                            action: () => this.openAgentSettings('memory', '_config')
                        },
                    ]
                }
            ];
        }
    }
}
</script>

<style scoped>
</style>
