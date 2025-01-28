<template>
    <v-tabs color="secondary" v-model="tab" :disabled="busy">
        <v-tab v-for="t in tabs" :key="t.value" :value="t.value">
            <v-icon start>{{ t.icon }}</v-icon>
            {{ t.title }}
        </v-tab>
    </v-tabs>
    <v-window v-model="tab">
        <v-window-item value="inference">
            <AppConfigPresetsInference ref="inference" :immutableConfig="immutableConfig" @update="() => $emit('update', config)"></AppConfigPresetsInference>
        </v-window-item>
        <v-window-item value="embeddings">
            <AppConfigPresetsEmbeddings 
            ref="embeddings" 
            @busy="() => busy = true"
            @done="() => busy = false"
            :memoryAgentStatus="agentStatus.memory || null" :immutableConfig="immutableConfig"
            :sceneActive="sceneActive"
            @update="() => $emit('update', config)"
            ></AppConfigPresetsEmbeddings>
        </v-window-item>
        <v-window-item value="system_prompts">
            <AppConfigPresetsSystemPrompts 
                ref="system_prompts"
                :immutableConfig="immutableConfig"
                :system-prompt-defaults="immutableConfig ? immutableConfig.system_prompt_defaults : {}"
                @update="() => $emit('update', config)"
            ></AppConfigPresetsSystemPrompts>
        </v-window-item>
    </v-window>
</template>
<script>
import AppConfigPresetsInference from './AppConfigPresetsInference.vue';
import AppConfigPresetsEmbeddings from './AppConfigPresetsEmbeddings.vue';
import AppConfigPresetsSystemPrompts from './AppConfigPresetsSystemPrompts.vue';

export default {
    name: 'AppConfigPresets',
    components: {
        AppConfigPresetsInference,
        AppConfigPresetsEmbeddings,
        AppConfigPresetsSystemPrompts,
    },
    props: {
        immutableConfig: Object,
        agentStatus: Object,
        sceneActive: Boolean,
    },
    emits: [
        'update',
    ],
    data() {
        return {
            tabs: [
                { title: 'Inference', icon: 'mdi-matrix', value: 'inference' },
                { title: 'Embeddings', icon: 'mdi-cube-unfolded', value: 'embeddings' },
                { title: 'System Prompts', icon: 'mdi-text-box', value: 'system_prompts' },
            ],
            tab: 'inference',
            busy: false,
        }
    },
    methods: {
        inference_config() {
            if(this.$refs.inference) {
                return this.$refs.inference.config.inference;
            }
            return null;
        },
        embeddings_config() {
            if(this.$refs.embeddings) {
                return this.$refs.embeddings.config.embeddings;
            }
            return null;
        },
        system_prompts_config() {
            if(this.$refs.system_prompts) {
                return this.$refs.system_prompts.config;
            }
            return null;
        },
    },
}

</script>