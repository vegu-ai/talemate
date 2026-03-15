<template>
    <div>
    <v-toolbar density="compact" flat color="mutedbg" class="chat-selector-toolbar">
        <v-select
            v-if="chatSelectItems.length > 0"
            :model-value="activeChatId"
            :items="chatSelectItems"
            item-title="title"
            item-value="value"
            density="compact"
            variant="solo-filled"
            flat
            hide-details
            :disabled="appBusy || !appReady"
            class="chat-select ml-5"
            @update:model-value="$emit('select-chat', $event)"
        />

        <v-tooltip text="New chat" location="top">
            <template v-slot:activator="{ props }">
                <v-btn
                    v-bind="props"
                    icon
                    size="small"
                    variant="text"
                    :disabled="appBusy || !appReady"
                    @click="$emit('start-chat')"
                >
                    <v-icon>mdi-plus</v-icon>
                </v-btn>
            </template>
        </v-tooltip>

        <v-btn color="delete" icon variant="text" size="small" :disabled="!activeChatId || appBusy || !appReady" @click="$emit('delete-chat')">
            <v-icon>mdi-delete-outline</v-icon>
            <v-tooltip activator="parent" location="top">Delete chat</v-tooltip>
        </v-btn>
    </v-toolbar>

    <v-toolbar density="compact" flat color="mutedbg">
        <v-toolbar-title class="text-subtitle-2 text-muted d-flex align-center" style="overflow: visible;">

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
                                class="ml-1"
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
                        class="ml-1"
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

    </v-toolbar>
    </div>

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
        chats: {
            type: Array,
            default: () => [],
        },
    },
    data() {
        return {
            usageCheatSheet: usageCheatSheet,
        }
    },
    emits: ['start-chat', 'delete-chat', 'update-mode', 'update-confirm-write-actions', 'select-chat'],
    computed: {
        modeOptions() {
            return {
                normal: { value: 'normal', title: 'Normal', icon: 'mdi-chat-processing', color: 'default' },
                decisive: { value: 'decisive', title: 'Decisive', icon: 'mdi-lightning-bolt', color: 'orange' },
                nospoilers: { value: 'nospoilers', title: 'No Spoilers', icon: 'mdi-emoticon-cool', color: 'primary' }
            }
        },
        chatSelectItems() {
            return this.chats.map(chat => {
                const shortId = (chat.id || '').substring(0, 4);
                return {
                    title: chat.title || `Untitled Chat (${shortId})`,
                    value: chat.id,
                };
            });
        },
    }
}
</script>

<style scoped>

.pre-wrap {
    white-space: pre-wrap;
}

.chat-selector-toolbar :deep(.v-toolbar__content) {
    padding-right: 0;
}

</style>


