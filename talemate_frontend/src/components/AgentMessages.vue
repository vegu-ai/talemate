<template>
    <v-btn icon variant="text" @click.stop="openDialog" :color="buttonColor" v-if="hasMessages" :size="buttonSize" class="agent-message-btn">
        <v-icon>mdi-message-text-outline</v-icon>
    </v-btn>
    <v-dialog v-model="dialog" :max-width="dialogMaxWidth">
        <v-card>
            <v-card-title>
                <v-icon size="small">mdi-message-text-outline</v-icon>
                {{ agentLabel }} Messages
            </v-card-title>
            <v-card-text>
                <v-list density="compact" slim :max-height="dialogMaxHeight" class="overflow-y-auto">
                    <v-list-item v-for="message in messages" :key="message.id">
                        <v-list-item-title>
                            <span :class="'text-' + message.data.color">{{ message.data.header }}</span>
                            <v-chip class="ml-2" v-for="(value, key) in message.meta" :key="key" size="x-small" variant="tonal" label>
                                <span class="mr-2">{{ key }}</span> {{ value }}
                            </v-chip>
                        </v-list-item-title>
                        <div class="text-muted text-caption agent-message-text" v-if="typeof message.message === 'string'">
                            {{ message.message }}
                        </div>
                        <v-list v-else>
                            <v-list-item v-for="(section, key) in message.message" :key="key">
                                <v-list-item-subtitle>{{ section.subtitle }}</v-list-item-subtitle>
                                <div v-if="typeof section.content === 'string'">
                                    <div v-if="section.process === 'diff'" v-html="section.content" class="text-muted text-caption agent-message-text"></div>
                                    <div v-else class="text-muted text-caption agent-message-text">
                                        {{ section.content }}
                                    </div>  
                                </div>
                                <div v-else-if="typeof section.content === 'object'">
                                    <div v-for="(item, index) in section.content" :key="index" class="text-muted text-caption agent-message-text">
                                       {{ item }}
                                    </div>
                                </div>
                                <div v-else>
                                    <div class="text-muted text-caption agent-message-text">
                                        {{ section.content }}
                                    </div>
                                </div>
                            </v-list-item>
                        </v-list>
                        <v-divider color="white"></v-divider>
                    </v-list-item>

                </v-list>
            </v-card-text>
        </v-card>
    </v-dialog>
</template>
<script>

export default {
    name: "AgentMessages",
    props: {
        messages: {
            type: Array,
            required: true
        },
        agent: {
            type: String,
            required: true
        },
        agentLabel: {
            type: String,
            default: "Agent"
        },
        messageReceiveTime: {
            type: Number,
            required: true
        }
    },
    computed: {
        hasMessages() {
            return this.messages.length > 0
        },
    },
    data() {
        return {
            dialog: false,
            dialogMaxWidth: "1920px",
            dialogMaxHeight: "1080px",
            buttonColor: "muted",
            buttonSize: "x-small",
            lastMessageId: null
        }
    },
    watch: {
        messageReceiveTime: {
            handler(val) {
                console.log("messageReceiveTime", val)
                this.pulseButton();
            },
            immediate: true
        }
    },
    methods: {
        openDialog() {
            this.dialog = true
        },
        pulseButton() {
            this.buttonColor = "highlight5";
            setTimeout(() => {
                this.buttonColor = "muted";
            }, 750);
        },
    },
}
</script>
<style scoped>
.agent-message-btn {
    transition: color 0.5s ease;
}
.agent-message-text {
    white-space: pre-wrap;
}

</style>
<style>
span.diff-delete {
    color: rgb(var(--v-theme-disabled));
}
.diff-insert {
    color: rgb(var(--v-theme-success));
}
</style>