<template>

    <v-card variant="text">
        <v-card-title class="ml-2">
            <v-icon size="x-small" class="mr-1" color="primary">mdi-alert-decagram</v-icon>
            What's new
            <v-icon @click="expand = true" v-if="!expand" class="ml-1">mdi-chevron-down</v-icon>
            <v-icon @click="expand = false" v-else class="ml-1">mdi-chevron-up</v-icon>
        </v-card-title>
        <v-expand-transition>
            <v-card-text v-show="expand">
                <v-row>
                    <v-col cols="2">
                        <div class="vertical-tabs">
                            <v-tabs v-model="selected" direction="vertical" color="secondary">
                                <v-tab v-for="item in whatsNew" :key="item.version" :value="item.version">
                                    {{ item.version }}
                                </v-tab>
                            </v-tabs>
                        </div>
                    </v-col>
                    <v-col cols="10">

                        <v-window v-model="selected">
                            <v-window-item v-for="item in whatsNew" :key="item.version" :value="item.version">

                                <v-row>
                                    <v-col cols="3" v-for="feature in item.items" :key="feature.title">
                                        <v-card color="muted-bg" class="solid">
                                            <v-card-title class="text-primary">{{ feature.title }}</v-card-title>
                                            <v-card-text class="text-white">
                                                <v-img 
                                                    v-if="feature.image" 
                                                    :src="require(`@/assets/${feature.image}`)" 
                                                    class="mb-3 rounded"
                                                    cover
                                                    height="150"
                                                ></v-img>
                                                <div class="content">{{ feature.description }}</div>
                                                <v-list v-if="feature.items" density="compact" bg-color="transparent">
                                                    <v-list-item v-for="(item, index) in feature.items" 
                                                        :key="index" 
                                                        class="text-caption text-muted">
                                                        {{ item }}
                                                    </v-list-item>
                                                </v-list>
                                                <p class="text-muted text-caption" v-if="feature.default_state">This feature is <span :class="'text-' + feature.default_state">{{feature.default_state }}</span> by default.</p>
                                            </v-card-text>
                                            <v-card-actions>
                                                <v-btn variant="text" color="primary"
                                                    @click="followLink(feature.link)" v-if="feature.link">Learn more</v-btn>
                                            </v-card-actions>
                                        </v-card>
                                    </v-col>
                                </v-row>

                            </v-window-item>
                        </v-window>

                    </v-col>
                </v-row>
            </v-card-text>
        </v-expand-transition>
    </v-card>


</template>

<script>

export default {
    name: 'WhatsNew',
    data() {
        return {
            expand: false,
            selected: "0.30.0",
            whatsNew: [
                {
                    version: '0.30.0',
                    items: [
                        {
                            title: "Node editor",
                            description: "The backend was refactored to a node based architecture, allowing for more complex and dynamic scenes and customizable / reusable modules.\n\nThis is the first iteration of the node editor and a lot of kinks still have to be worked out. The node editor is accessible from the creative mode once a scene is loaded.\n\nI am aware that there is no good way to export / import node modules yet, but this will be added in a future version.",
                            image: "node-editor-preview.png"
                        },
                        {
                            title: "Revisions",
                            description: "Revision action added to the Editor agent. This action, when toggled on, whill analyze text for repetition or unwanted prose and revise it accordingly. Unwanted prose is defined through the writing style template assigned in the scene settings.",
                            default_state: "disabled",
                            link: ["agent", "editor", "revision"]
                        },
                        {
                            title: "Auto-Direction",
                            description: "The Director agent can now automatically direct the scene based on the current state and intention of the scene. \n\nThis is experimental and a work in progress.\n\nThe goal is to test the waters towards giving the reigns to the Director agent to direct the scene as it sees fit.",
                            default_state: "disabled",
                            link: ["agent", "director", "auto_direct"]
                        },
                        {
                            title: "Noteable improvements",
                            description: "A lot of smaller improvements and bug fixes.",
                            items: [
                                "Inference preset groups",
                                "AI function calling improvements",
                                "Client rate limiting",
                                "Clients can now configure data communication to be in YAML or JSON format",
                                "Simulation Suite V2 - remade using the new node editor (v1 still exists)",
                                "Director guidance cache",
                            ]
                        }
                    ]
                },
                {
                    version: '0.29.0',
                    items: [
                        {
                            title: "Scene analysis",
                            description: "Added scene analysis capabilities, providing analytical summaries that other agents can use to enhance their output.",
                            default_state: "disabled",
                            link: ["agent", "summarizer", "analyze_scene"]
                        },
                        {
                            title: "Director Guidance",
                            description: "The director agent now offers conversation and narration guidance based on the summarizer's scene analysis.",
                            default_state: "disabled",
                            link: ["agent", "director", "guide_scene"]
                        },
                        {
                            title: "Character Progress",
                            description: "The world state agent can now automatically track character progress and provide proposals of updates to the character description and attributes.",
                            default_state: "disabled",
                            link: ["agent", "world_state", "character_progression"]
                        }
                    ]
                }
            ]
        }
    },
    inject: ['openAgentSettings'],
    methods: {
        followLink(link) {
            if(link[0] === "agent") {
                this.openAgentSettings(link[1], link[2]);
            }
        }
    }
}

</script>
<style scoped>
.vertical-tabs {
    height: 100%;
}
.vertical-tabs :deep(.v-tabs) {
    height: 100%;
}
.vertical-tabs :deep(.v-tab) {
    min-width: 100%;
    justify-content: flex-start;
}
.content {
    white-space: pre-wrap;
}
</style>