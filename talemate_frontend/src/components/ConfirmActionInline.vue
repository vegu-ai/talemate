<template>
        <v-btn v-if="confirming===false" 
            :disabled="disabled" 
            :color="color" 
            :size="size"
            variant="text" 
            @click.stop="initiateAction" 
            :icon="iconOnly"
            :density="density"
            :prepend-icon="!iconOnly ? icon : undefined"
        >
            <v-icon v-if="iconOnly">{{ icon }}</v-icon>
            <template v-else>
                {{ actionLabel }}
            </template>
        </v-btn>
        <v-btn v-if="confirming===true"
            :color="color" 
            variant="text" 
            :size="size"
            @click.stop="confirmAction" 
            :icon="iconOnly"
            :density="density"
            :prepend-icon="!iconOnly ? icon : undefined"
        >
            <v-icon v-if="iconOnly">{{ icon }}</v-icon>
            <template v-else>
                {{ confirmLabel }}
            </template>
        </v-btn>
        <v-btn v-if="confirming===true"
            :class="vertical ? '' : 'ml-1'" 
            color="cancel" 
            variant="text" 
            :size="size"
            @click.stop="cancelAction" 
            :icon="iconOnly"
            :density="density"
            :prepend-icon="!iconOnly ? icon : undefined"
        >
            <v-icon v-if="iconOnly">mdi-cancel</v-icon>
            <template v-else>
                Cancel
            </template>
        </v-btn>
</template>
<script>

export default {
    name: "ConfirmActionInline",
    props:{
        actionLabel: String,
        confirmLabel: String,
        disabled: Boolean,
        vertical: Boolean,
        density: {
            type: String,
            default: 'default',
            validator: (value) => ['default', 'compact', 'comfortable'].includes(value)
        },
        size: {
            type: String,
            default: 'default',
            validator: (value) => ['x-small', 'small', 'default', 'large', 'x-large'].includes(value)
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
    computed: {
        iconOnly() {
            return this.density === 'compact' || this.density === 'comfortable';
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