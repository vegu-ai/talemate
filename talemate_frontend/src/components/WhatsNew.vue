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
                                                <div v-if="feature.items" class="items-list">
                                                    <div v-for="(item, index) in feature.items"
                                                        :key="index"
                                                        class="item-entry">
                                                        <span class="bullet">•</span>
                                                        <span class="item-text">{{ item }}</span>
                                                    </div>
                                                </div>
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
            selected: "0.35.0",
            whatsNew: [
                {
                    version: '0.35.0',
                    items: [
                        {
                            title: "Autonomous Scene Direction",
                            description: "Allows autonomous scene progression through the director agent, using the same actions available in director chat.\n\nThe Direction tab shows actions taken during the director's turn. A strong LLM (100B+) with reasoning capabilities is recommended.\n\nNew director actions can be added via Director Action Nodes in the node editor.",
                            default_state: "disabled"
                        },
                        {
                            title: "Character Visuals & Avatars",
                            description: "New Visuals tab in the character editor for managing portraits and cover images with generation support.\n\nCharacter messages now display portraits. The world state manager can re-evaluate which portrait to use based on scene context and commission new portraits via the director."
                        },
                        {
                            title: "Inline Visuals",
                            description: "Images created through scene tools or director actions now appear inline in the scene feed. Size and display options can be configured in appearance settings."
                        },
                        {
                            title: "llama.cpp & Pocket TTS",
                            description: "Added official llama.cpp client support for llama-server.\n\nPocket TTS support added for local CPU-based text-to-speech with voice cloning using audio prompts."
                        },
                        {
                            title: "Notable Improvements",
                            items: [
                                "Setup wizard on initial launch for LLM, Memory and Visual agent configuration",
                                "Message appearance overhaul with configurable markdown display",
                                "KoboldCpp: adaptive-p, min-p, presence/frequency penalty support",
                                "Pin conditions can now target game state variables",
                                "Visual: resolution presets, prompt revision, auto analysis, prompt length config",
                                "Visual Library: image crop regions for cover images",
                                "Experimental concurrent requests for hosted clients (visual prompts)",
                                "Agent activity stack visible above scene tools",
                                "Node editor shortcuts: X for staging/alignment, Y for vertical alignment"
                            ]
                        }
                    ]
                },
                {
                    version: '0.34.1',
                    items: [
                        {
                            title: "OpenRouter Reasoning Model Fixes",
                            description: "Fixed issues with OpenRouter reasoning models.",
                            items: [
                                "Fix empty responses from reasoning models",
                                "Fix reasoning token not found errors",
                                "Let OpenRouter handle reasoning token collection",
                                "Configure reasoning effort correctly"
                            ]
                        }
                    ]
                },
                {
                    version: '0.34.0',
                    items: [
                        {
                            title: "Visual Agent Refactor",
                            description: "Visual agent refactor adds image editing with reference images and image analysis capabilities. Image editing allows modifying existing images using reference images. Image analysis extracts information from images for use in generation.\n\nSupported backends: ComfyUI, Automatic1111, SD.Next, OpenAI, Google, OpenRouter.\n\nVisual prompt instruction can now be customized through new Visual Style templates in the Templates editor.\n\nNodes for image image generation have been added to the node editor."
                        },
                        {
                            title: "Visual Library",
                            description: "Visual library system for managing generated images and scene assets. Includes character portraits, scene covers, and other generated images. The image queue allows generating new images, regenerating existing ones, and iterating on generated images with modifications.\n\nNodes for asset management have been added to the node editor."
                        },
                        {
                            title: "Character Card Support",
                            description: "Character card import system completely refactored. Director agent analyzes greeting texts to detect multiple characters present in the card, allowing selective import of detected characters.\n\nAlternate greetings can be imported as episodes with optional AI-generated titles.\n\nCharacter books (lore books) are imported as world state entries.\n\nCharacter generation now uses card description, greeting texts, and character book entries together to determine character descriptions, attributes, and dialogue examples.\n\nPlayer character can be set using a default template, selected from detected characters in the card, or imported from another scene."
                        },
                        {
                            title: "Noteable improvements",
                            description: "A lot of smaller improvements and bug fixes.",
                            items: [
                                "The `Templates` editor has been moved out of the World Editor and is now available from the main navigation and no longer requires a scene to be loaded.",
                                "Scene assets are now managed in a separate file that all scenes in the same project share (assets/library.json)",
                                "Fix issue where narrator would use wrong preset / system message",
                                "Prompt for unified api key configuration during client setup",
                                "Improved token/s calculation",
                                "Add Reset shortcut to Save menu",
                                "Add save required indicator to save menu",
                                "Fixed \"'_SceneRef' object has no attribute '_changelog'\" error",
                                "Client selection in agent config will now only show enabled clients",
                                "App now properly locks inputs when client configuration is missing",
                                "Improvements to director chat",
                                "Fixes character image generation missing information if the targeted character is inactive",
                                "Shared world: button to share/unshare all characters",
                                "Shared world: button to share/unshare all world entries",
                                "Shared world: added episodes which is basically just talemate's version of alternate introductions",
                                "Narrator: story progress now respects the generation length setting in the narrator agent config",
                                "Character state reinforcements: added require_active setting that requires the character to be active for the state to be reprocessed. This defaults to true."
                            ]
                        },
                    ]
                },
                {
                    version: '0.33.0',
                    items: [
                        {
                            title: "Director Chat",
                            description: "A chat interface for conversing with the Director agent about the current scene. The Director can execute actions through 25+ specialized node modules covering scene queries, character/world state updates, game state management, narrative direction, and history modifications.\n\nMinimum recommended parameters: 12k+ context, 32B+ model with reasoning enabled. Ideally 100B+ models for best results.\n\nAccessible through the director console once a scene is loaded."
                        },
                        {
                            title: "Scene Changelog and Restoration",
                            description: "Tracks all scene changes over time using delta compression. Stores incremental changes between revisions in segmented changelog files. This allows scenes to be reconstructed fully to a specific point in history and will be used for restoring scenes as well as true forking of scenes."
                        },
                        {
                            title: "Shared World Context",
                            description: "Allows marking characters, world entries, and static history entries as \"shared\" to synchronize them across multiple scenes in the same project.\n\nShared elements are exported to a dedicated context file that other scenes can reference. For characters, supports granular sharing at the attribute and detail level.\n\nShared context files can be created and managed in World Editor -> Scene -> Shared Context."
                        },
                        {
                            title: "Noteable improvements",
                            items: [
                                "Agent persona (only for director currently)",
                                "Pin decay - pin will stay active for N turns without having to be re-evaluated",
                                "Improvements to data structure handling in LLM responses",
                                "Game state variable editor",
                                "ContextID system for unified management of context",
                                "Pressing ctrl+up arrow/down arrow will cycle through previous messages in the scene chat input",
                                "Added summarizer / editor / director message access to scene toolbar",
                                "Scene forking function will now use the new changelog system to reconstruct the scene to the specified revision",
                                "World Editor -> Context DB has been made read only (other than pin management)",
                                "Memory agent semantic retrieval improvements"
                            ]
                        },
                        {
                            title: "Bug fixes",
                            items: [
                                "Fixed issue where drag and drop scene / character cover images would no longer work",
                                "Some layout issues in world editor",
                                "Enforce Context DB clean up on scene load",
                                "Openrouter api key going from unset to set will immediately fetch models",
                                "Fixed remaining \"World state manager\" references in the UX to \"World Editor\"",
                                "Scenes that no longer exist are automatically removed from recent scenes list",
                                "Contextual generate will default to the scene writing style if its set",
                                "Fix ai function argument conversation that would cast everything to string"
                            ]
                        },
                        {
                            title: "Node Editor",
                            items: [
                                "Many new nodes have been added to the node editor",
                                "Module library overhaul to treeview display in sidebar",
                                "Show when required inputs are not connected (red links)",
                                "Certain nodes can now be ALT+SHIFT+Dragged to spawn a counterpart",
                                "Collector nodes for easier collection of values into lists or dicts",
                                "Clicking outside of node property editor will no longer discard changes automatically",
                                "Errors in event nodes should no longer be allowed to cause infinite loops of failures",
                                "Deleting a module while its loaded will no longer result in an error",
                                "Fixed issue where argument nodes would not convert to their type correctly",
                                "Switching from node editor to world editor will no longer cause the changes to the graph to be lost",
                                "Node search improvements",
                                "Get node can now properly access tuple and set items",
                                "Auto resize new nodes to fit their title and inputs",
                                "Node property choice fields are now sorted alphabetically",
                                "Added group presets",
                                "Contextual Generate node will now error nicely when the required context_name is not set",
                                "Fix issue where Ctrl+Enter to submit in text editor nodes would cause extra new lines to be added"
                            ]
                        }
                    ]
                },
                {
                    version: '0.32.3',
                    items: [
                        {
                            title: "Bugfix release",
                            description: "Node editor context menu positioning fix.",
                            items: [
                                "Fix LiteGraph context menu positioning issue"
                            ]
                        }
                    ]
                },
                {
                    version: '0.32.2',
                    items: [
                        {
                            title: "Bugfix release",
                            description: "Bug fixes and connection improvements.",
                            items: [
                                "Fix KoboldCpp connection issues"
                            ]
                        }
                    ]
                },
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
.items-list {
    margin-top: 12px;
}
.item-entry {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    margin-bottom: 6px;
    font-size: 0.75rem;
    color: rgba(255, 255, 255, 0.6);
}
.bullet {
    flex-shrink: 0;
    line-height: 1.2;
}
.item-text {
    line-height: 1.2;
}
</style>