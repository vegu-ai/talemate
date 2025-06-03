<template>
    <v-dialog v-model="confirming" :max-width="maxWidth" :contained="contained">
        <v-card>
            <v-card-title class="headline">
                <v-icon class="mr-2" size="small">{{ icon }}</v-icon>
                {{ actionLabel }}
            </v-card-title>
            <v-card-text v-html="formattedDescription">
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="muted" text @click="cancelAction">
                    {{ cancelText }}
                </v-btn>
                <v-btn :color="color" text @click="confirmAction">
                    {{ confirmText }}
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>
<script>

export default {
    name: "ConfirmActionPrompt",
    props:{
        confirmText: {
            type: String,
            default: 'Yes'
        },
        cancelText: {
            type: String,
            default: 'No'
        },
        actionLabel: String,
        description: String,
        icon: {
            type: String,
            default: 'mdi-close-box-outline'
        },
        color: {
            type: String,
            default: 'delete'
        },
        contained: {
            type: Boolean,
            default: false,
        },
        maxWidth: {
            type: Number,
            default: 290
        }
    },
    emits: ['confirm', 'cancel'],
    data(){
        return{
            confirming: false,
            params: null,
        }
    },
    computed: {
        formattedDescription() {
            if (!this.description || !this.params) return this.description;
            
            return this.description.replace(/{([^}]+)}/g, (match, key) => {
                const value = this.params && this.params[key] !== undefined ? this.params[key] : '';
                return `<span class="text-primary">${value}</span>`;
            });
        }
    },
    methods:{
        initiateAction(params) {
            this.confirming = true;
            this.params = params;
        },
        confirmAction(){
            this.confirming = false;
            this.$emit('confirm', this.params)
        },
        cancelAction(){
            this.confirming = false;
            this.$emit('cancel', this.params)
        }
    }
}

</script>