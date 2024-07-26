<template>
    <div v-if="confirming===false">
        <v-btn :disabled="disabled" rounded="sm" :prepend-icon="icon" :color="color" variant="text" @click.stop="initiateAction" >
            {{ actionLabel}}
        </v-btn>
    </div>
    <div v-else>
        <v-btn rounded="sm" :prepend-icon="icon" @click.stop="confirmAction"  :color="color" variant="text">
            {{ confirmLabel }}
        </v-btn>
        <v-btn class="ml-1" rounded="sm" prepend-icon="mdi-cancel" @click.stop="cancelAction" color="cancel" variant="text">
            Cancel
        </v-btn>
    </div>
</template>
<script>

export default {
    name: "ConfirmActionInline",
    props:{
        actionLabel: String,
        confirmLabel: String,
        disabled: Boolean,
        icon: {
            type: String,
            default: 'mdi-close-box-outline'
        },
        color: {
            type: String,
            default: 'delete'
        }
    },
    emits: ['confirm', 'cancel'],
    data(){
        return{
            confirming: false,
        }
    },
    methods:{
        initiateAction(){
            this.confirming = true;
        },
        confirmAction(){
            this.confirming = false;
            this.$emit('confirm')
        },
        cancelAction(){
            this.confirming = false;
            this.$emit('cancel')
        }
    }
}

</script>