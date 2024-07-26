<template>
    <CoverImage 
        ref="coverImageScene" 
        :target="scene" 
        type="scene" 
        :collapsable="false"
        :allow-update="true"
    />
</template>
<script>
import CoverImage from './CoverImage.vue';

export default {
    components: {
        CoverImage,
    },
    name: 'WorldStateManagerMenuSceneTools',
    props: {
        scene: Object,
        manager: Object,
        worldStateTemplates: Object,
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    data() {
        return {

        }
    },
    watch: {
    },
    computed: {
    },
    emits: [
        'world-state-manager-navigate'
    ],
    methods: {
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}

</script>