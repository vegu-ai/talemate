<template>
    <v-list density="compact" slim>
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-history</v-icon>
            Recent Templates
            <v-spacer />
            <v-btn
                icon
                size="x-small"
                variant="text"
                @click="refresh"
                :loading="loading"
            >
                <v-tooltip activator="parent" location="top">Refresh</v-tooltip>
                <v-icon>mdi-refresh</v-icon>
            </v-btn>
        </v-list-subheader>

        <v-list-item
            v-for="template in recentTemplates"
            :key="template.uid"
            @click="navigateToTemplate(template)"
        >
            <v-list-item-title class="text-caption">{{ template.uid }}</v-list-item-title>
            <template #append>
                <v-chip size="x-small" label variant="outlined">{{ template.source_group }}</v-chip>
            </template>
        </v-list-item>

        <v-list-item v-if="!loading && recentTemplates.length === 0">
            <v-list-item-subtitle class="text-caption">No recent templates</v-list-item-subtitle>
        </v-list-item>
    </v-list>
</template>

<script>
export default {
    name: "PromptsMenu",
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    data() {
        return {
            recentTemplates: [],
            loading: false,
        }
    },
    emits: ['navigate-template'],
    methods: {
        refresh() {
            this.loading = true;
            const websocket = this.getWebsocket();
            if (websocket) {
                websocket.send(JSON.stringify({
                    type: 'prompts',
                    action: 'get_recent_templates'
                }));
            }
        },
        navigateToTemplate(template) {
            this.$emit('navigate-template', template);
        },
        handleMessage(message) {
            if (message.type !== 'prompts') {
                return;
            }
            if (message.action === 'get_recent_templates') {
                this.recentTemplates = message.data?.templates || [];
                this.loading = false;
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.refresh();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>
