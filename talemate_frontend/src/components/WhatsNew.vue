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
                                    <v-col cols="12" sm="6" md="6" lg="4" xl="3" xxl="2" v-for="feature in item.items" :key="feature.title">
                                        <v-card color="muted-bg" class="solid">
                                            <v-card-title class="text-primary">{{ feature.title }}</v-card-title>
                                            <v-card-text class="text-white">
                                                <v-img 
                                                    v-if="feature.image" 
                                                    :src="getImageSrc(feature.image)" 
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
                                                <v-spacer></v-spacer>
                                                <a :href="feature.changelog" target="_blank" v-if="feature.changelog"><v-icon class="mr-1">mdi-open-in-new</v-icon>Changelog</a>
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
            selected: "0.32.1",
            whatsNew: [
                {
                    version: '0.32.1',
                    items: [
                        {
                            title: "Bugfix release",
                            description: "Bug fixes and minor improvements.",
                            items: [
                                "Fix LMStudio connection (#212)",
                                "Fix Windows setup failure when any parent folder path contains spaces (#211)",
                                "Fix character creation issues",
                                "Tweak scene analysis and director guidance prompts for conversation",
                                "Add GLM 4.5 templates"
                            ]
                        }
                    ]
                },
                {
                    version: '0.32.0',
                    items: [
                        {
                            title: "TTS Agent refactor",
                            description: "The Text-to-Speech agent has been completely refactored, adding support for additional APIs, per-character voice assignment and speaker separation. Voices can now be managed through the new voice library.",
                            items: [
                                "Local: F5-TTS (zero shot voice cloning), Chatterbox (zero shot voice cloning), Kokoro (predefined voice models)",
                                "Remote: ElevenLabs, Google Gemini-TTS, OpenAI",
                                "Director agent can automatically assign voices to new characters based on voice library tags",
                                "XTTS2 support removed"
                            ]
                        },
                        {
                            title: "Reasoning / Thinking models",
                            description: "Support for reasoning / thinking models has been added across all client types. Activate it via the new Reasoning tab in the client configuration UI.",
                            default_state: "disabled"
                        },
                        {
                            title: "Scene export / import packages",
                            description: "Scenes can now be exported as complete packages—including nodes, assets and info files—and imported through the home view. Stand-alone JSON scene files remain supported for backward compatibility."
                        },
                        {
                            title: "Noteable improvements",
                            description: "Smaller features and bug fixes",
                            items: [
                                "Simulation suite: fix inactive characters",
                                "OpenRouter: provider selection and generation quality fixes",
                                "Fix Jinja2 error during auto direction generation",
                                "KoboldCpp client default template added",
                                "Agents can be ctrl-clicked to toggle enabled state",
                                "Visual agent: prevent scene cover image overwrite",
                                "Disable scene analysis / guidance when building image generation prompts",
                                "Migration from vue-cli to Vite (thanks @pax-co)",
                                "Underlying config handling refactor improving stability"
                            ]
                        },
                        {
                            title: "Node Editor",
                            description: "New nodes have been added to the node editor.",
                            items: [
                                "As String node",
                                "Generate TTS node",
                                "Get Narrator Voice node",
                                "Get Voice node",
                                "TTS Agent settings node",
                                "Unpack voice node"
                            ]
                        },
                    ]
                },
                {
                    version: '0.31.0',
                    items: [
                        {
                            title: "Installable node modules.",
                            description: "Added very rudimentary way to register node modules as packages so they can be installed into a scene.\n\nA mods tab becomes available once a scene is loaded and allows installing / uninstalling of such modules. The Dynamic Story node module has had a package added to that effect and you should no longer need to mess with the node editor to set it up in a scene.",
                        },
                        {
                            title: "History Management",
                            description: "Can now add, edit, remove and regenerate entries in the History tab of the World Editor.\n\nEntries based on summarization can be inspected to show their source messages.",
                        },
                        {
                            title: "Noteable improvements",
                            description: "Bug-fixes and improvements",
                            items: [
                                "Instructor Embeddigns are once again functional",
                                "OpenRouter support added",
                                "Ollama support added",
                                "KoboldCpp Embeddings support added",
                                "Visual agent can now generate prompts only. This is available even if the visual agent is not fully configured for image generation",
                                "Memory Agent - memory retrieval has been improved",
                                "Summarization Agent - summarization improvements",
                                "chara_card_v3 spec character card import fixed",
                            ],
                            changelog: "https://github.com/vegu-ai/talemate/pull/193"
                        },
                        {
                            title: "Node Editor",
                            description: "Node editor bug-fixes and improvements.",
                            items: [
                                "fixes issue where errors inside custom node graphs could hang talemate",
                                "fixes issues with a bunch of math nodes that would cause them to run even though the wires to them were inactive",
                                "fix issue with DynamicInstruction node that would cause it to run even though the wires to it were inactive",
                                "fix issue where editor revision events were missing the `template_vars` value",
                                "jinja2 templates existing in templates/modules can now be properly loaded",
                                "Emit System Message node - allows for communication of messages to the user outside of the context history",
                            ],
                            changelog: "https://github.com/vegu-ai/talemate/pull/193"
                        }
                    ]
                },
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
        getImageSrc(image) {
            try {
                return new URL(`../assets/${image}`, import.meta.url).href;
            } catch (e) {
                console.warn('Image not found:', image);
                return '';
            }
        },
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