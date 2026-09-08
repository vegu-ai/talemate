<template>
    <v-tooltip :text="tooltipText" location="top" max-width="400" class="pre-wrap">
        <template v-slot:activator="{ props }">
            <v-btn
                v-bind="props"
                color="primary"
                variant="text"
                :prepend-icon="effectiveIcon"
                :disabled="disabled"
                @click.stop="ask"
            >{{ label }}</v-btn>
        </template>
    </v-tooltip>
</template>

<script>
import { ASK_AGENTS, askAgent } from '@/utils/askAgent';

export default {
    name: 'AskAgent',
    inject: ['openDirectorConsole', 'openHelpChat'],
    props: {
        agent: {
            type: String,
            required: true,
            validator: (value) => value in ASK_AGENTS,
        },
        label: {
            type: String,
            required: true,
        },
        icon: {
            type: String,
            required: false,
            default: null,
        },
        prompt: {
            type: String,
            required: true,
        },
        disabled: {
            type: Boolean,
            required: false,
            default: false,
        },
    },
    computed: {
        effectiveIcon() {
            return this.icon || ASK_AGENTS[this.agent]?.icon;
        },
        tooltipText() {
            return `Starts a new ${this.agent} chat and asks:\n\n${this.prompt}`;
        },
    },
    methods: {
        ask() {
            // the prompt is stored before the drawer opens: the help chat only
            // mounts with its drawer, and it reads the prompt as it comes up
            if(!askAgent(this.agent, this.prompt)) return;
            if(this.agent === 'help') {
                this.openHelpChat();
            } else {
                this.openDirectorConsole();
            }
        },
    },
}
</script>

<style scoped>
.pre-wrap {
    white-space: pre-wrap;
}
</style>
