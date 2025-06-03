<template>
    <div v-if="confirming===false">
        <v-btn 
            :disabled="disabled" 
            rounded="sm" 
            :color="color" 
            variant="text" 
            @click.stop="initiateAction" 
            :icon="density === 'compact'"
        >
            <v-icon v-if="density === 'compact'">{{ icon }}</v-icon>
            <template v-else>
                <v-icon start>{{ icon }}</v-icon>
                {{ actionLabel }}
            </template>
        </v-btn>
    </div>
    <div v-else>
        <v-btn 
            rounded="sm" 
            :color="color" 
            variant="text" 
            @click.stop="confirmAction" 
            :icon="density === 'compact'"
        >
            <v-icon v-if="density === 'compact'">{{ icon }}</v-icon>
            <template v-else>
                <v-icon start>{{ icon }}</v-icon>
                {{ confirmLabel }}
            </template>
        </v-btn>
        <v-btn 
            class="ml-1" 
            rounded="sm" 
            color="cancel" 
            variant="text" 
            @click.stop="cancelAction" 
            :icon="density === 'compact'"
        >
            <v-icon v-if="density === 'compact'">mdi-cancel</v-icon>
            <template v-else>
                <v-icon start>mdi-cancel</v-icon>
                Cancel
            </template>
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
        density: {
            type: String,
            default: 'default',
            validator: (value) => ['default', 'compact'].includes(value)
        },
        icon: {
            type: String,
            default: 'mdi-close-circle-outline'
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