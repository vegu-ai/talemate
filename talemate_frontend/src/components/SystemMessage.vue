<template>
    <v-alert :variant="display" closable :color="color" density="compact" :icon="icon" class="mb-3 text-caption">
        <v-alert-title v-if="title">{{ title }}</v-alert-title>
        <div class="message-body" v-if="!as_markdown">
            {{ message }}
        </div>
        <div class="message-body" v-else v-html="renderedMarkdown"></div>
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
    computed: {
        renderedMarkdown() {
            return marked.parse(this.message);
        },
    },
}
</script>

<style scoped>
.message-body {
    white-space: pre-wrap;
}
</style>