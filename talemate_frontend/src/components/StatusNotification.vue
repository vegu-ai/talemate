<template>
    <v-snackbar v-model="statusMessage" location="top" :color="notificationColor()" close-on-content-click :timeout="notificationTimeout()" elevation="5">
        <template v-slot:actions>
            <v-btn v-if="cancellable" color="delete" rounded="0" elevation="0" variant="text" @click="cancel"><v-icon>mdi-cancel</v-icon></v-btn>
        </template>

        <v-progress-circular v-if="statusMessageType === 'busy'" indeterminate="disable-shrink" color="primary" size="20"></v-progress-circular>
        <v-icon v-else>{{ notificationIcon() }}</v-icon>
        <span class="ml-2">{{ statusMessageText }}</span>
    </v-snackbar>
</template>

<script>

export default {
    data() {
        return {
            statusTitle: '',
            statusMessage: false,
            statusMessageText: '',
            statusMessageType: '',
            cancellable: false,
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput'],
    methods: {

        cancel: function() {
            this.getWebsocket().send(JSON.stringify({type: 'interrupt'}));
        },

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
                    return 'orange-darken-4';
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
                    this.cancellable = data.data && data.data.cancellable;
                }
            }
        },
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>