<template>
    <v-menu>
        <template v-slot:activator="{ props }">
            <v-progress-circular class="ml-1 mr-1" size="24" v-if="agentStatus.visual && agentStatus.visual.busy" indeterminate="disable-shrink"
            color="secondary"></v-progress-circular>   
            <v-btn v-else class="hotkey mx-1" v-bind="props" :disabled="disabled" color="primary" icon variant="text">
                <v-icon>mdi-image-frame</v-icon>
            </v-btn>
        </template>
        <v-list>
            <v-list-subheader>Visualize</v-list-subheader>
            <div v-if="!visualAgentReady">
                <v-alert type="warning" density="compact" variant="text" class="mb-3 text-caption">Visual agent is not ready for image generation, will output prompt instead.</v-alert>
            </div>
            <!-- environment -->
            <v-list-item @click="(event) => generateEnvironmentImage(event.ctrlKey)" prepend-icon="mdi-image-filter-hdr">
                <v-list-item-title>Visualize Environment <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">Ctrl: Prompt Only</v-chip></v-list-item-title>
                <v-list-item-subtitle>Generate a background image of the environment</v-list-item-subtitle>
            </v-list-item>
            <!-- npcs -->
            <v-list-item v-for="npc_name in npcCharacters" :key="npc_name"
                @click="(event) => generateCharacterImage(npc_name, event.ctrlKey)" prepend-icon="mdi-brush">
                <v-list-item-title>Visualize {{ npc_name }} <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">Ctrl: Prompt Only</v-chip></v-list-item-title>
                <v-list-item-subtitle>Generate a portrait of {{ npc_name }}</v-list-item-subtitle>
            </v-list-item>
        </v-list>
    </v-menu>
</template>
<script>

export default {
    name: 'SceneToolsVisual',
    props: {
        agentStatus: {
            type: Object,
            required: true,
        },
        disabled: {
            type: Boolean,
            required: true,
        },
        visualAgentReady: {
            type: Boolean,
            required: true,
        },
        npcCharacters: {
            type: Array,
            required: true,
        },
    },

    data() {
        return {
        }
    },

    inject: ['getWebsocket'],

    methods: {
        generateCharacterImage(character_name, prompt_only = false) {
            this.getWebsocket().send(JSON.stringify({
                type: 'visual',
                action: 'visualize_character',
                context: {
                    character_name: character_name,
                    prompt_only: prompt_only,
                },
            }));
        },
        generateEnvironmentImage(prompt_only = false) {
            this.getWebsocket().send(JSON.stringify({
                type: 'visual',
                action: 'visualize_environment',
                context: {
                    prompt_only: prompt_only,
                },
            }));
        },
    }
}
</script>