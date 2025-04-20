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
                <v-list density="compact" slim max-height="600" class="overflow-y-auto">
                    <v-list-item v-for="message in messages" :key="message.id">
                        <v-list-item-subtitle>
                            <span :class="'text-' + message.data.color">{{ message.data.header }}</span>
                            <v-chip class="ml-2" v-for="(value, key) in message.meta" :key="key" size="x-small" variant="tonal" label>
                                <span class="text-caption mr-2">{{ key }}</span> {{ value }}
                            </v-chip>
                        </v-list-item-subtitle>
                        <div class="text-muted text-caption">
                            {{ message.message }}
                        </div>
                        <v-divider></v-divider>
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
            required: true
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
            dialogMaxWidth: "1024px",
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
</style>