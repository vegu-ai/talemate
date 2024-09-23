<template>
    <v-snackbar v-model="statusMessage" location="top" :color="notificationColor()" close-on-content-click :timeout="notificationTimeout()" elevation="5">
        <v-progress-circular v-if="statusMessageType === 'busy'" indeterminate="disable-shrink" color="primary" size="20"></v-progress-circular>
        <v-icon v-else>{{ notificationIcon() }}</v-icon>
        <span class="ml-2">{{ statusMessageText }}</span>

    </v-snackbar>
</template>

<script>

export default {
    data() {
        return {
            statusMessage: false,
            statusMessageText: '',
            statusMessageType: '',
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput'],
    methods: {


        notificationTimeout: function() {
            switch(this.statusMessageType) {
                case 'busy':
                    return -1;
                case 'error':
                    return 8000;
                default:
                    return 3000;
            }
        },

        notificationIcon: function() {
            switch(this.statusMessageType) {
                case 'success':
                    return 'mdi-check-circle';
                case 'error':
                    return 'mdi-alert-circle';
                case 'warning':
                    return 'mdi-alert-circle';
                case 'info':
                    return 'mdi-information';
                default:
                    return 'mdi-information';
            }
        },

        notificationColor: function() {
            switch(this.statusMessageType) {
                case 'success':
                    return 'success';
                case 'error':
                    return 'red-darken-2';
                case 'warning':
                    return 'warning';
                case 'info':
                    return 'info';
                default:
                    return 'grey-darken-4';
            }
        },

        handleMessage(data) {
            if(data.type === 'status') {

                if(data.data && data.data.as_scene_message)
                    return;

                if(data.status === 'idle' && this.statusMessageType === 'busy') {
                    this.statusMessage = false;
                    this.statusMessageText = '';
                    this.statusMessageType = '';
                } else {
                    this.statusMessage = true;
                    this.statusMessageText = data.message;
                    this.statusMessageType = data.status;
                }
            }
        },
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>