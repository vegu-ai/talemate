<template>
    <div>
        <v-row>
            <v-col cols="12" sm="8" xxl="5">
                <v-text-field 
                    v-model="template.name" 
                    label="Writing style name" 
                    :rules="[v => !!v || 'Name is required']"
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                    required>
                </v-text-field>
                
                <v-text-field 
                    v-model="template.description" 
                    label="Template description" 
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                    required>
                </v-text-field>
                
                <v-textarea 
                    v-model="template.instructions"
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                    auto-grow rows="5" 
                    placeholder="Use a narrative writing style that reminds of mid 90s point and click adventure games."
                    label="Writing style instructions"
                    hint="Instructions for the AI on how to apply this writing style to the generated content."
                >
                </v-textarea>
            </v-col>
            <v-col cols="12" sm="4" xxl="7">
                <v-checkbox 
                    v-model="template.favorite" 
                    label="Favorite" 
                    @update:model-value="save"
                    messages="Favorited writing styles will appear on the top of the list.">
                </v-checkbox>
            </v-col>
        </v-row>
        
        <v-card class="mt-4">
            <v-card-title>
                <v-icon size="small" class="mr-2">mdi-text-box-search</v-icon>
                Phrase Detection
                <v-chip label size="x-small" color="grey" class="ml-2">
                    {{ phrasesCount }} phrases
                </v-chip>
            </v-card-title>
            <v-card-text>
                <p class="text-caption mb-4">
                    Add phrases that should be detected in the generated content. 
                    When these phrases are found, the AI may apply the specified instructions.
                </p>

                <v-alert v-if="hasAnyWithSemanticSimilarity" class="text-caption mb-4 text-muted" variant="text" icon="mdi-information-outline">
                    <p class="text-uppercase">
                        <strong class="text-warning">Some phrases are using semantic similarity.</strong> 
                    </p>
                    <p>
                        Such phrases will be compared using the embedding model selected in the <span class="text-primary">Memory Agent</span>.
                    </p>
                    <p class="mt-2">
                         This has the potential to do <b class="text-warning">A LOT of requests to the embedding model</b> as <b class="text-warning">each sentence in the content is compared to each phrase</b>. Batching is used when available, but its not advisable to use this with remote embedding APIs at this point (openai etc.).
                    </p>
                    <p class="mt-2">
                        When running with local embeddings, using the gpu by setting the device to <b class="text-success">CUDA</b> is recommended.
                    </p>
                </v-alert>
                
                <v-table v-if="template.phrases && template.phrases.length > 0">
                    <thead>
                        <tr>
                            <th class="td-active">Active</th>
                            <th>Phrase</th>
                            <th class="td-instructions">Instructions</th>
                            <th class="td-type">Match method</th>
                            <th class="td-type">Classification</th>
                            <th class="td-actions text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="(phrase, index) in template.phrases" :key="index">
                            <td>
                                <v-checkbox
                                    v-model="phrase.active"
                                    density="compact"
                                    hide-details
                                    color="primary"
                                    @update:model-value="save"
                                ></v-checkbox>
                            </td>
                            
                            <td v-if="editIndex === index">
                                <v-text-field v-model="editPhrase.phrase" variant="underlined" density="compact" hide-details></v-text-field>
                            </td>
                            <td v-else>{{ phrase.phrase }}</td>
                            
                            <td v-if="editIndex === index">
                                <v-textarea v-model="editPhrase.instructions" variant="underlined" density="compact" hide-details auto-grow rows="1"></v-textarea>
                            </td>
                            <td v-else>{{ phrase.instructions }}</td>

                            <td v-if="editIndex === index">
                                <v-select
                                    v-model="editPhrase.match_method"
                                    :items="matchMethodOptions"
                                    variant="underlined"
                                    density="compact"
                                    hide-details
                                ></v-select>
                            </td>
                            <td v-else>{{ phrase.match_method }}</td>

                            <td v-if="editIndex === index">
                                <v-select
                                    v-model="editPhrase.classification"
                                    :items="classificationOptions"
                                    variant="underlined"
                                    density="compact"
                                    hide-details
                                ></v-select>
                            </td>
                            <td v-else>{{ phrase.classification }}</td>
                            
                            <td class="text-right">
                                <div class="d-flex justify-end">
                                    <v-btn variant="text" v-if="editIndex === index" icon size="small" color="success" @click="updatePhrase">
                                        <v-icon>mdi-check</v-icon>
                                    </v-btn>
                                    <v-btn variant="text" v-if="editIndex === index" icon size="small" color="error" class="ml-2" @click="cancelEdit">
                                        <v-icon>mdi-close</v-icon>
                                    </v-btn>
                                    <v-btn variant="text" v-if="editIndex !== index" icon size="small" color="primary" @click="startEdit(index)">
                                        <v-icon>mdi-pencil</v-icon>
                                    </v-btn>
                                    <v-btn variant="text" icon size="small" color="primary" class="ml-2" @click="duplicatePhrase(index)">
                                        <v-icon>mdi-content-copy</v-icon>
                                    </v-btn>
                                    <v-btn variant="text" icon size="small" color="delete" class="ml-2" @click="removePhrase(index)">
                                        <v-icon>mdi-delete</v-icon>
                                    </v-btn>
                                </div>
                            </td>
                        </tr>
                    </tbody>
                </v-table>
                <v-alert v-else type="info" color="grey" variant="text" class="mt-2 mb-2">
                    No phrases defined. Add a phrase below.
                </v-alert>
                
                <v-form @submit.prevent="addPhrase" class="mt-4">
                    <v-divider class="mb-4"></v-divider>
                    <v-row>
                        <v-col cols="12" md="8">
                            <v-text-field v-model="newPhrase" label="Phrase" required hint="The phrase to detect (supports regex)"></v-text-field>
                        </v-col>
                        <v-col cols="12" md="2">
                            <v-select
                                v-model="newMatchMethod"
                                :items="matchMethodOptions"
                                label="Match method"
                                required
                                hint="How should this phrase be matched"
                            ></v-select>
                        </v-col>
                        <v-col cols="12" md="2">
                            <v-select
                                v-model="newClassification"
                                :items="classificationOptions"
                                label="Classification"
                                required
                                hint="How should this phrase be classified"
                            ></v-select>
                        </v-col>
                    </v-row>
                    <v-textarea rows="3" auto-grow v-model="newInstructions" label="Instructions" required hint="Instructions on what to do when the phrase is detected"></v-textarea>
                    <v-btn type="submit" variant="text" prepend-icon="mdi-plus" color="primary" class="mt-2">Add phrase</v-btn>
                </v-form>
            </v-card-text>
        </v-card>
    </div>
</template>

<script>
export default {
    name: 'WorldStateManagerTemplateWritingStyle',
    props: {
        immutableTemplate: {
            type: Object,
            required: true
        }
    },
    computed: {
        phrasesCount() {
            return this.template.phrases ? this.template.phrases.length : 0;
        },
        hasAnyWithSemanticSimilarity() {
            return this.template.phrases.some(phrase => phrase.match_method === 'semantic_similarity');
        }
    },
    watch: {
        immutableTemplate: {
            handler(newVal) {
                this.template = {
                    ...newVal,
                    phrases: Array.isArray(newVal.phrases) ? [...newVal.phrases].map(phrase => ({
                        ...phrase,
                        active: phrase.active === undefined ? true : phrase.active
                    })) : []
                }
            },
            deep: true,
            immediate: true
        }
    },
    data() {
        return {
            template: {
                name: '',
                description: '',
                instructions: '',
                phrases: [],
                favorite: false
            },
            dirty: false,
            newPhrase: '',
            newInstructions: '',
            newClassification: 'unwanted',
            newMatchMethod: 'regex',
            editIndex: -1,
            editPhrase: {
                phrase: '',
                instructions: '',
                classification: 'unwanted',
                match_method: 'regex',
                active: true
            },
            classificationOptions: [
                { title: 'Unwanted', value: 'unwanted' }
            ],
            matchMethodOptions: [
                { title: 'Regex', value: 'regex' },
                { title: 'Semantic similarity (embedding)', value: 'semantic_similarity' }
            ]
        }
    },
    emits: ['update'],
    methods: {
        addPhrase() {
            if (!this.newPhrase || !this.newInstructions) return;
            
            if (!this.template.phrases) {
                this.template.phrases = [];
            }
            
            this.template.phrases.push({
                phrase: this.newPhrase,
                instructions: this.newInstructions,
                classification: this.newClassification,
                match_method: this.newMatchMethod,
                active: true
            });
            
            this.newPhrase = '';
            this.newInstructions = '';
            this.newClassification = 'unwanted';
            this.newMatchMethod = 'regex';
            this.dirty = true;
            this.save();
        },
        removePhrase(index) {
            this.template.phrases.splice(index, 1);
            this.dirty = true;
            this.save();
        },
        duplicatePhrase(index) {
            const originalPhrase = this.template.phrases[index];
            const duplicatedPhrase = { ...originalPhrase };
            this.template.phrases.splice(index + 1, 0, duplicatedPhrase);
            this.dirty = true;
            this.save();
        },
        startEdit(index) {
            this.editIndex = index;
            this.editPhrase = {
                phrase: this.template.phrases[index].phrase,
                instructions: this.template.phrases[index].instructions,
                classification: this.template.phrases[index].classification || 'unwanted',
                match_method: this.template.phrases[index].match_method || 'regex',
                active: this.template.phrases[index].active === undefined ? true : this.template.phrases[index].active
            };
        },
        updatePhrase() {
            if (!this.editPhrase.phrase || !this.editPhrase.instructions) return;
            
            this.template.phrases[this.editIndex] = {
                phrase: this.editPhrase.phrase,
                instructions: this.editPhrase.instructions,
                classification: this.editPhrase.classification || 'unwanted',
                match_method: this.editPhrase.match_method || 'regex',
                active: this.editPhrase.active === undefined ? true : this.editPhrase.active
            };
            
            this.editIndex = -1;
            this.dirty = true;
            this.save();
        },
        cancelEdit() {
            this.editIndex = -1;
        },
        save() {
            this.dirty = false;
            this.$emit('update', this.template);
        }
    },
    created() {
        this.template = {
            ...this.immutableTemplate,
            phrases: this.immutableTemplate.phrases ? [...this.immutableTemplate.phrases].map(phrase => ({
                ...phrase,
                active: phrase.active === undefined ? true : phrase.active
            })) : []
        };
    }
}
</script>

<style scoped>
.td-instructions {
    width: 30%;
}
.td-type {
    width: 200px;
}
.td-actions {
    width: 100px;
}
.td-active {
    width: 80px;
}
</style> 