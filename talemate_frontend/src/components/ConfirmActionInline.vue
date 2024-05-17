<template>
    <div v-if="confirming===false">
        <v-btn :disabled="disabled" rounded="sm" prepend-icon="mdi-close-box-outline" color="delete" variant="text" @click.stop="initiateAction" >
            {{ actionLabel}}
        </v-btn>
    </div>
    <div v-else>
        <v-btn rounded="sm" prepend-icon="mdi-close-box-outline" @click.stop="confirmAction"  color="delete" variant="text">
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