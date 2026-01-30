<template>
    <v-list density="compact" slim>
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-history</v-icon>
            Recent Templates
        </v-list-subheader>
        <v-card variant="text" class="mb-2">
            <v-card-text class="text-caption text-muted pa-2">
                Templates that recently generated prompts to the LLM. Click to navigate to the template source for editing.
                <v-divider class="my-2"></v-divider>
                Default templates are read-only. To override, create a copy in the <strong>user</strong> group or a custom group.
            </v-card-text>
        </v-card>
        <v-btn
            block
            prepend-icon="mdi-refresh"
            variant="text"
            color="primary"
            :loading="loading"
            @click="refresh"
        >Refresh</v-btn>

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
    props: {
        active: {
            type: Boolean,
            default: false,
        },
    },
    data() {
        return {
            recentTemplates: [],
            loading: false,
        }
    },
    emits: ['navigate-template'],
    watch: {
        active(newVal) {
            if (newVal) {
                this.refresh();
            }
        },
    },
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
