<template>
    <v-alert :variant="display" closable :color="color" density="compact" :icon="icon" class="mb-3 text-caption" @click:close="handleClose">
        <v-alert-title v-if="title">{{ title }}</v-alert-title>
        <div class="message-body message-body-plain" v-if="!as_markdown">
            {{ message }}
        </div>
        <div class="message-body message-body-markdown" v-else v-html="renderedMarkdown"></div>
    </v-alert>
</template>
<script>
import { marked } from 'marked';

export default {
    name: 'SystemMessage',
    props: {
        message: {
            type: String,
            required: true,
        },
        messageId: {
            type: String,
            required: false,
        },
        color: {
            type: String,
            required: false,
            default: "info",
        },
        icon: {
            type: String,
            required: false,
            default: "mdi-information-outline",
        },
        title: {
            type: String,
            required: false,
        },
        display: {
            type: String,
            required: true,
            default: "text",
        },
        as_markdown: {
            type: Boolean,
            required: false,
            default: false,
        },
    },
    emits: ['close'],
    computed: {
        renderedMarkdown() {
            return marked.parse(this.message);
        },
    },
    methods: {
        handleClose() {
            this.$emit('close', this.messageId);
        },
    },
}
</script>

<style scoped>
.message-body-plain {
    white-space: pre-wrap;
}

.message-body-markdown :deep(ul),
.message-body-markdown :deep(ol) {
    padding-left: 24px;
}

</style>