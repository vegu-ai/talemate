<template>
    <v-dialog v-model="open" :max-width="size" :contained="contained">
        <v-card>
            <v-card-title>
                <v-icon v-if="icon" size="small" class="mr-2" color="primary">{{ icon }}</v-icon>
                <span class="headline">{{ title }}</span>
            </v-card-title>
            <v-card-text>

                <v-alert v-if="instructions" color="muted" variant="text">
                    <div class="instructions">{{ instructions }}</div>
                </v-alert>

                <v-form @submit.prevent="proceed" ref="form" v-model="valid">
                    <v-row v-if="inputType === 'multiline'">
                        <v-col cols="12">
                            <v-textarea
                                v-model="input"
                                ref="input_multiline"
                                @keydown.enter.ctrl="proceed"
                                @keydown.enter.meta="proceed"
                                :placeholder="placeholder"
                                :label="title"
                                :rules="combinedRules"
                                :messages="`Press ${primaryModifierLabel}+Enter to submit`"
                            ></v-textarea>
                        </v-col>
                    </v-row>
                    <v-row v-else>
                        <v-col cols="12">
                            <v-text-field
                                v-model="input"
                                ref="input_text"
                                @keydown.enter.ctrl="proceed"
                                @keydown.enter.meta="proceed"
                                :label="title"
                                :placeholder="placeholder"
                                :rules="combinedRules"
                                :messages="`Press ${primaryModifierLabel}+Enter to submit`"
                            ></v-text-field>
                        </v-col>
                    </v-row>
                </v-form>
            </v-card-text>
            <v-card-actions>
                <v-btn @click="cancel" color="muted" prepend-icon="mdi-cancel">
                    Cancel
                </v-btn>
                <v-spacer></v-spacer>
                <v-btn @click="proceed" color="primary" prepend-icon="mdi-check-circle-outline" :disabled="!valid">
                    Continue
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import { primaryModifierLabel } from '@/utils/keyboardModifiers';

export default {
    name: "RequestInput",
    props: {
        title: String,
        instructions: String,
        icon: String,
        placeholder: {
            type: String,
            default: '',
        },
        contained: {
            type: Boolean,
            default: false,
        },
        size: {
            type: Number,
            default: 500,
        },
        inputType: {
            type: String,
            default: 'text',
        },
        // Extra Vuetify-style validation rules to apply on top of the
        // built-in `required` check. Each rule is `(value) => true | string`,
        // returning a message when invalid. The Continue button is disabled
        // until every rule passes.
        rules: {
            type: Array,
            default: () => [],
        },
    },
    computed: {
        combinedRules() {
            return [this.builtInRules.required, ...this.rules];
        },
    },
    data() {
        return {
            primaryModifierLabel,
            open: false,
            valid: false,
            extra_params: {},
            input: '',
            builtInRules: {
                required: value => !!value || 'Required.',
            }
        }
    },
    emits: ['continue', 'cancel'],

    methods: {
        proceed() {
            this.$refs.form.validate()
            if(!this.valid) {
                return;
            }

            this.$emit('continue', this.input, this.extra_params);
            this.open = false;
        },
        cancel() {
            this.$emit('cancel');
            this.open = false;
        },
        openDialog(extra_params) {
            this.open = true;
            this.extra_params = extra_params || {};
            this.input = extra_params?.input || '';
            // auto focus on input next tick
            this.$nextTick(() => {
                if(this.inputType === 'multiline') {
                    this.$refs.input_multiline.focus();
                } else {
                    this.$refs.input_text.focus();
                }
            });
        }
    }
}


</script>

<style scoped>
.instructions {
    white-space: pre-wrap;
}
</style>