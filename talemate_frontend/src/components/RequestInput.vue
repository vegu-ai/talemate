<template>
    <v-dialog v-model="open" max-width="500">
        <v-card>
            <v-card-title>
                <span class="headline">{{ title }}</span>
            </v-card-title>
            <v-card-text>
                <v-form>
                    <v-row v-if="inputType === 'multiline'">
                        <v-col cols="12">
                            <v-textarea
                                v-model="input"
                                :label="title"
                            ></v-textarea>
                        </v-col>
                    </v-row>
                    <v-row v-else>
                        <v-col cols="12">
                            <v-text-field
                                v-model="input"
                                :label="title"
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
                <v-btn @click="proceed" color="primary" prepend-icon="mdi-check-circle-outline">
                    Continue
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>

export default {
    name: "RequestInput",
    props: {
        title: String,
        inputType: {
            type: String,
            default: 'text',
        },
    },
    data() {
        return {
            open: false,
            input: '',
        }
    },
    emits: ['continue', 'cancel'],

    methods: {
        proceed() {
            this.$emit('continue', this.input);
            this.open = false;
        },
        cancel() {
            this.$emit('cancel');
            this.open = false;
        },
        openDialog() {
            this.open = true;
            this.input = '';
        }
    }
}


</script>