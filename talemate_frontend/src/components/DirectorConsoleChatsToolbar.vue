<template>
    <v-toolbar density="compact" flat color="mutedbg">
        <v-toolbar-title class="text-subtitle-2 text-muted">
            <v-tooltip v-if="activeChatId" text="Select chat mode" location="top">
                <template v-slot:activator="{ props: tooltipProps }">
                    <v-menu>
                        <template v-slot:activator="{ props: menuProps }">
                            <v-chip
                                v-bind="Object.assign({}, menuProps, tooltipProps)"
                                size="small"
                                :color="modeOptions[mode].color"
                                label
                                clickable
                                class="ml-2"
                                :disabled="appBusy || !appReady"
                            >
                                <v-icon start>{{ modeOptions[mode].icon }}</v-icon>
                                {{ modeOptions[mode].title }}
                                <v-icon end>mdi-chevron-down</v-icon>
                            </v-chip>
                        </template>
                        <v-list density="compact">
                            <v-list-item
                                v-for="modeOption in modeOptions"
                                :key="modeOption.value"
                                @click="$emit('update-mode', modeOption.value)"
                                :active="mode === modeOption.value"
                            >
                                <template v-slot:prepend>
                                    <v-icon>{{ modeOption.icon }}</v-icon>
                                </template>
                                <v-list-item-title>{{ modeOption.title }}</v-list-item-title>
                            </v-list-item>
                        </v-list>
                    </v-menu>
                </template>
            </v-tooltip>

            <v-tooltip v-if="activeChatId" text="Toggle write-action confirmation" location="top">
                <template v-slot:activator="{ props }">
                    <v-chip
                        :disabled="appBusy"
                        v-bind="props"
                        size="small"
                        class="ml-2"
                        :color="confirmWriteActions ? 'success' : 'warning'"
                        label
                        clickable
                        @click="$emit('update-confirm-write-actions', !confirmWriteActions)"
                    >
                        <v-icon start>{{ confirmWriteActions ? 'mdi-shield-check' : 'mdi-shield-off-outline' }}</v-icon>
                        {{ confirmWriteActions ? 'Confirm On' : 'Confirm Off' }}
                    </v-chip>
                </template>
            </v-tooltip>

            <DirectorActionsMenu 
                v-if="activeChatId"
                mode="chat"
                :app-busy="appBusy"
                :app-ready="appReady"
            />

        </v-toolbar-title>



        <v-tooltip text="Tokens / Scene Context Max. / Chat Context Max." location="top" v-if="tokens != null" >
            <template v-slot:activator="{ props }">
                <v-chip size="small" class="mr-2" variant="text" color="muted" label v-bind="props">
                    <v-icon start>mdi-counter</v-icon>
                    {{ tokens }}            
                    <span class="mx-1">/</span>

                    <span v-if="budgets">{{ budgets.scene_context }}</span>
                    <span v-else>-</span>

                    <span class="mx-1">/</span>

                    <span v-if="budgets">{{ budgets.director_chat }}</span>
                    <span v-else>-</span>
                </v-chip>
            </template>
        </v-tooltip>

        <v-tooltip :text="usageCheatSheet" location="top" max-width="300" class="pre-wrap">
            <template v-slot:activator="{ props }">
                <v-icon v-bind="props" color="muted">mdi-information-outline</v-icon>
            </template>
        </v-tooltip>

        <v-btn color="delete" icon variant="text" :disabled="!activeChatId || appBusy || !appReady" @click="$emit('clear-chat')">
            <v-icon>mdi-close-circle-outline</v-icon>
            <v-tooltip activator="parent" location="top">Clear chat</v-tooltip>

        </v-btn>
    </v-toolbar>

</template>

<script>
import DirectorActionsMenu from './DirectorActionsMenu.vue';

const usageCheatSheet = "Chat with the director about the story.\n\nPlan what to do next, ask it to make changes or retrieve information.\n\nThis is a new, experimental feature and can absolutely destroy your scene. Save often.\n\nAbsolute minimum recommended parameters: 12k+ context, 32B+ model with reasoning enabled. Operating with smaller LLMs can work, but requests need to be specific and sessions short.\n\nIdeally, aim for 100B+ models."

export default {
    name: 'DirectorConsoleChatsToolbar',
    components: {
        DirectorActionsMenu,
    },
    props: {
        activeChatId: {
            type: [String, Number, Object],
            default: null,
        },
        tokens: {
            type: Number,
            default: null,
        },
        mode: {
            type: String,
            default: 'normal',
        },
        budgets: {
            type: Object,
            default: null,
        },
        confirmWriteActions: {
            type: Boolean,
            default: true,
        },
        appBusy: {
            type: Boolean,
            default: false,
        },
        appReady: {
            type: Boolean,
            default: true,
        },
    },
    data() {
        return {
            usageCheatSheet: usageCheatSheet,
        }
    },
    emits: ['start-chat', 'clear-chat', 'update-mode', 'update-confirm-write-actions'],
    computed: {
        modeOptions() {
            return {
                normal: { value: 'normal', title: 'Normal', icon: 'mdi-chat-processing', color: 'default' },
                decisive: { value: 'decisive', title: 'Decisive', icon: 'mdi-lightning-bolt', color: 'orange' },
                nospoilers: { value: 'nospoilers', title: 'No Spoilers', icon: 'mdi-emoticon-cool', color: 'primary' }
            }
        },
    }
}
</script>

<style scoped>

.pre-wrap {
    white-space: pre-wrap;
}


</style>


