<template>
    <div>
        <v-row>
            <v-col cols="12" sm="8" xxl="5">
                <v-text-field 
                    v-model="template.name" 
                    label="Persona name" 
                    :rules="[v => !!v || 'Name is required']"
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                    required>
                </v-text-field>

                <v-text-field 
                    v-model="template.description" 
                    label="Description" 
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save">
                </v-text-field>

                <v-textarea 
                    v-model="template.instructions"
                    label="Persona instructions"
                    hint="E.g., You are Frank the fantasy nerd, you love making dark and gritty D&D campaigns."
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                    auto-grow
                    rows="5">
                </v-textarea>

                <v-textarea 
                    v-model="template.initial_chat_message"
                    label="Initial Director chat message (optional)"
                    hint="Overrides the first director message when starting or clearing a chat. Supports {player_name}."
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                    auto-grow
                    rows="3">
                </v-textarea>
            </v-col>
            <v-col cols="12" sm="4" xxl="7">
                <v-checkbox 
                    v-model="template.favorite" 
                    label="Favorite" 
                    @update:model-value="save">
                </v-checkbox>

            </v-col>
        </v-row>
    </div>
</template>

<script>
export default {
    name: 'TemplateAgentPersona',
    props: {
        immutableTemplate: {
            type: Object,
            required: true
        }
    },
    data() {
        return {
            template: {
                name: '',
                description: '',
                instructions: '',
                initial_chat_message: '',
                favorite: false
            },
            dirty: false,
        }
    },
    emits: ['update'],
    watch: {
        immutableTemplate: {
            handler(newVal) {
                this.template = {
                    name: newVal.name || '',
                    description: newVal.description || '',
                    instructions: newVal.instructions || '',
                    initial_chat_message: newVal.initial_chat_message || '',
                    favorite: !!newVal.favorite,
                    uid: newVal.uid,
                    group: newVal.group,
                    template_type: newVal.template_type || 'agent_persona',
                    priority: newVal.priority || 1,
                }
            },
            immediate: true,
            deep: true,
        }
    },
    methods: {
        save() {
            this.dirty = false;
            this.$emit('update', this.template);
        }
    }
}
</script>


