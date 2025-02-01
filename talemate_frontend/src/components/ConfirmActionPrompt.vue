<template>
    <v-dialog v-model="confirming" max-width="290">
        <v-card>
            <v-card-title class="headline">
                <v-icon class="mr-2" size="small">{{ icon }}</v-icon>
                {{ actionLabel }}
            </v-card-title>
            <v-card-text>
                {{ description }}
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
    },
    emits: ['confirm', 'cancel'],
    data(){
        return{
            confirming: false,
            params: null,
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