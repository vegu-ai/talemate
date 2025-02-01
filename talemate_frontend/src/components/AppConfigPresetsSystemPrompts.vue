<template>

    <v-row>
        <v-col :cols="(scope == 'client' ? 3 : 4)">
            <v-list density="compact">

                <v-tabs v-model="tab" density="compact" color="highlight5">
                    <v-tab v-for="t in availableTabs" :key="t.value" :value="t.value">
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
        <v-col :cols="(scope == 'client' ? 9 : 8)">

            <v-card v-if="selectedKey !== null">
                <v-card-text>
                    <div class="text-right">
                        <v-btn color="primary" @click="applyDefault" size="x-small" variant="text">Apply Default</v-btn>
                    </div>
                    <v-textarea
                        v-model="config[selectedKey]"
                        :placeholder="systemPromptDefaults ? systemPromptDefaults[selectedKey] : ''"
                        rows="10"
                        auto-grow
                        clearable
                        @update:model-value="dropIfEmpty(selectedKey);"
                        @blur="$emit('update', {system_prompts: config})"
                        :label="labelFromValue(selected[0], tab === 'decensor')"
                    ></v-textarea>
                </v-card-text>

                
                <v-alert v-if="tab == 'decensor'" density="compact" color="primary" variant="text">
                    <p class="text-caption text-grey mt-4">
                        <v-icon color="warning" class="mr-2">mdi-alert</v-icon>Only local API clients will currently make use of the <span class="text-primary">uncensored</span> prompts. A toggle will be added for more control of this in the future.
                    </p>
                </v-alert>
            </v-card>

            <v-alert v-else-if="scope=='app'" density="compact" color="primary" variant="text" class="mt-10">
                <p>
                    App wide override for the various system prompts based on action type.
                </p>
                <p class="text-caption text-grey">
                    These will be used when there are no client specific overrides configured in the client.
                </p>
            </v-alert>

            <v-alert v-else-if="scope=='client'" density="compact" color="primary" variant="text" class="mt-10">
                <p>
                    Client specific override for the various system prompts based on action type.
                </p>
                <p class="text-caption text-grey">
                    These system prompts will only be used by this client.
                </p>
                <p class="text-caption text-grey">
                    You can specify global overrides in the <span class="text-primary"><v-icon>mdi-cog</v-icon> Settings</span> window.
                </p>
            </v-alert>
        </v-col>
    </v-row>

</template>

<script>

export default {
    name: 'AppConfigPresetsSystemPrompts',
    props: {
        immutableConfig: Object,
        systemPromptDefaults: Object,
        scope: {
            type: String,
            default: 'app',
        },
        decensorAvailable: {
            type: Boolean,
            default: true,
        }
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
        availableTabs() {
            return this.tabs.filter(t => t.condition());
        },
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
                { title: 'Normal', value: 'normal', condition: ()=> { return (this.scope == 'app' || !this.decensorAvailable) } },
                { title: 'Uncensored', value: 'decensor', condition: ()=> { return (this.scope == 'app' || this.decensorAvailable) } },
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
            if(this.systemPromptDefaults && this.selectedKey in this.systemPromptDefaults) {
                this.config[this.selectedKey] = this.systemPromptDefaults[this.selectedKey];
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