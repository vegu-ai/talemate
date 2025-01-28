<template>

    <v-row>
        <v-col cols="4">
            <v-list density="compact">

                <v-tabs v-model="tab" density="compact" color="highlight5">
                    <v-tab v-for="t in tabs" :key="t.value" :value="t.value">
                        {{ t.title }}
                    </v-tab>
                </v-tabs>

                <v-list selectable color="primary" v-model:selected="selected">
                    <v-list-item v-for="item in systemPromptKindList" :key="item.value" :value="item.value">
                        <v-list-item-title>{{ item.label }}</v-list-item-title>
                    </v-list-item>
                </v-list>
            </v-list>
        </v-col>
        <v-col cols="8">

            <v-card v-if="selectedKey !== null">
                <v-card-text>
                    <div class="text-right">
                        <v-btn color="primary" @click="applyDefault" size="x-small" variant="text">Apply Default</v-btn>
                    </div>
                    <v-textarea
                        v-model="config[selectedKey]"
                        :placeholder="immutableConfig.system_prompt_defaults ? immutableConfig.system_prompt_defaults[selectedKey] : ''"
                        rows="5"
                        auto-grow
                        clearable
                        @update:model-value="dropIfEmpty(selectedKey); $emit('update', {system_prompts: config})"
                        :label="labelFromValue(selected[0], tab === 'decensor')"
                    ></v-textarea>
                </v-card-text>

                
                <v-alert v-if="tab == 'decensor'" density="compact" color="primary" variant="text">
                    <p class="text-caption text-grey mt-4">
                        <v-icon color="warning" class="mr-2">mdi-alert</v-icon>Only local API clients will currently make use of the <span class="text-primary">uncensored</span> prompts. A toggle will be added for more control of this in the future.
                    </p>
                </v-alert>
            </v-card>

            <v-alert v-else density="compact" color="primary" variant="text" class="mt-10">
                <p>
                    App wide override for the various system prompts based on action type.
                </p>
                <p class="text-caption text-grey">
                    These will be used when there are no client specific overrides configured in the client.
                </p>
            </v-alert>
        </v-col>
    </v-row>

</template>

<script>

/*
    roleplay: str | None = None
    narrator: str | None = None
    creator: str | None = None
    director: str | None = None
    analyst: str | None = None
    analyst_freeform: str | None = None
    editor: str | None = None
    world_state: str | None = None
    summarize: str | None = None
    visualize: str | None = None
    
    roleplay_decensor: str | None = None
    narrator_decensor: str | None = None
    creator_decensor: str | None = None
    director_decensor: str | None = None
    analyst_decensor: str | None = None
    analyst_freeform_decensor: str | None = None
    editor_decensor: str | None = None
    world_state_decensor: str | None = None
    summarize_decensor: str | None = None
    visualize_decensor: str | None = None
*/

export default {
    name: 'AppConfigPresetsSystemPrompts',
    props: {
        immutableConfig: Object
    },
    watch: {
        immutableConfig: {
            handler: function(newVal) {
                if(!newVal) {
                    this.config = {};
                    return;
                }
                this.config = {...newVal.system_prompts};
            },
            immediate: true,
            deep: true,
        },
    },
    emits: [
        'update',
    ],
    computed:{
        selectedKey() {
            // selected[0] will hold the kind
            // if tab is decensor, append _decensor
            return this.selected.length > 0 ? this.selected[0]+(this.tab === 'decensor' ? '_decensor' : '') : null;
        }
    },
    data() {
        return {
            tab: "normal",
            tabs: [
                { title: 'Normal', value: 'normal' },
                { title: 'Uncensored', value: 'decensor' },
            ],
            config: {
            },
            selected: [],
            systemPromptKindList: [
                {label: 'Conversation', value: 'roleplay'},
                {label: 'Narration', value: 'narrator'},
                {label: 'Creation', value: 'creator'},
                {label: 'Direction', value: 'director'},
                {label: 'Analysis (JSON)', value: 'analyst'},
                {label: 'Analysis Freeform', value: 'analyst_freeform'},
                {label: 'Editing', value: 'editor'},
                {label: 'World State', value: 'world_state'},
                {label: 'Summarization', value: 'summarize'},
            ]
        }
    },
    methods: {

        dropIfEmpty(key) {
            if(this.config[key] === '') {
                delete this.config[key];
            }
        },

        applyDefault() {
            if(this.immutableConfig.system_prompt_defaults && this.selectedKey in this.immutableConfig.system_prompt_defaults) {
                this.config[this.selectedKey] = this.immutableConfig.system_prompt_defaults[this.selectedKey];
            }
        },

        labelFromValue(value, decensor=false) {
            for(let item of this.systemPromptKindList) {
                if(item.value === value) {
                    return item.label+(decensor ? ' (Uncensored)' : '');
                }
            }
            return value;
        }
    }
}

</script>