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
    </v-window>
</template>
<script>
import AppConfigPresetsInference from './AppConfigPresetsInference.vue';
import AppConfigPresetsEmbeddings from './AppConfigPresetsEmbeddings.vue';

export default {
    name: 'AppConfigPresets',
    components: {
        AppConfigPresetsInference,
        AppConfigPresetsEmbeddings,
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
    },
}

</script>