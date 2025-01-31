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
                        <v-tabs v-model="selected" vertical color="secondary">
                            <v-tab v-for="item in whatsNew" :key="item.version" :value="item.version" block>
                                {{ item.version }}
                            </v-tab>
                        </v-tabs>
                    </v-col>
                    <v-col cols="10">

                        <v-window v-model="selected">
                            <v-window-item v-for="item in whatsNew" :key="item.version" :value="item.version">

                                <v-row>
                                    <v-col cols="3" v-for="feature in item.items" :key="feature.title">
                                        <v-card color="muted-bg" class="solid">
                                            <v-card-title class="text-primary">{{ feature.title }}</v-card-title>
                                            <v-card-text class="text-white">
                                                {{ feature.description }}
                                                <p class="text-muted text-caption">
                                                    This feature is <span :class="'text-' + feature.default_state">{{
                                                        feature.default_state }}</span> by default.
                                                </p>
                                            </v-card-text>
                                            <v-card-actions>
                                                <v-btn variant="text" color="primary"
                                                    @click="followLink(feature.link)">Learn more</v-btn>
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
            selected: "0.29.0",
            whatsNew: [
                {
                    version: '0.29.0',
                    items: [
                        {
                            title: "Scene analysis",
                            description: "The summarizer agent now includes scene analysis capabilities, providing analytical summaries that other agents can use to enhance their output.",
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
                            default_state: "enabled",
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

</style>