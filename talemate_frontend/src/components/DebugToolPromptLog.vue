<template>
    <v-list-subheader class="text-uppercase"><v-icon>mdi-post-outline</v-icon> Prompts
        <v-chip size="x-small" color="primary">{{ max_prompts }}</v-chip>
        <v-icon color="primary" class="ml-2" @click="clearPrompts">mdi-close</v-icon>
    </v-list-subheader>

    <v-list-item density="compact">
        <v-slider density="compact" v-model="max_prompts" min="1" hide-details max="250" step="1" color="primary"></v-slider>
    </v-list-item>

    <v-list-item v-for="(prompt, index) in prompts" :key="index" @click="openPromptView(prompt)">
        <v-list-item-title class="text-caption">

            <v-row>
                <v-col cols="2" class="text-info">#{{ prompt.num }}</v-col>
                <v-col cols="10" class="text-right">{{ prompt.kind }}</v-col>
            </v-row>

        </v-list-item-title>
        <v-list-item-subtitle>
            <v-chip size="x-small" class="mr-1" color="primary">{{ prompt.prompt_tokens }}<v-icon size="14"
            class="ml-1">mdi-arrow-down-bold</v-icon></v-chip>
            <v-chip size="x-small" class="mr-1" color="secondary">{{ prompt.response_tokens }}<v-icon size="14"
            class="ml-1">mdi-arrow-up-bold</v-icon></v-chip>
            <v-chip size="x-small">{{ prompt.time }}s<v-icon size="14" class="ml-1">mdi-clock</v-icon></v-chip>
        </v-list-item-subtitle>
        <v-divider class="mt-1"></v-divider>
    </v-list-item>

    <DebugToolPromptView ref="promptView" />
</template>
<script>

import DebugToolPromptView from './DebugToolPromptView.vue';

export default {
    name: 'DebugToolPromptLog',
    data() {
        return {
            prompts: [],
            total: 1,
            max_prompts: 50,
        }
    },
    components: {
        DebugToolPromptView,
    },
    inject: [
        'getWebsocket', 
        'registerMessageHandler', 
        'setWaitingForInput',
    ],

    methods: {
        clearPrompts() {
            this.prompts = [];
            this.total = 0;
        },
        handleMessage(data) {

            if(data.type === "system"&& data.id === "scene.loaded") {
                this.prompts = [];
                this.total = 0;
                return;
            }

            if(data.type === "prompt_sent") {
                // add to prompts array, and truncate if necessary (max 50)
                this.prompts.unshift({
                    prompt: data.data.prompt,
                    response: data.data.response,
                    kind: data.data.kind,
                    response_tokens: data.data.response_tokens,
                    prompt_tokens: data.data.prompt_tokens,
                    time: parseInt(data.data.time),
                    num: this.total++,
                })

                while(this.prompts.length > this.max_prompts) {
                    this.prompts.pop();
                }
            }
        },

        openPromptView(prompt) {
            this.$refs.promptView.open(prompt);
        }
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },

}

</script>