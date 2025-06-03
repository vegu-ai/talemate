<template>
    <v-alert 
        variant="text" 
        :color="notificationColor()" 
        class="text-center text-caption">
        {{ text }}
        <p v-if="status == 'busy'">
            <v-progress-linear color="primary" height="2" indeterminate></v-progress-linear>
        </p>
    </v-alert>
</template>

<script>
export default {
    name: 'StatusMessage',
    data() {
        return {
        }
    },
    props: {
        text: String,
        status: String,
        isLastMessage: Boolean,
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput'],
    methods: {
        notificationIcon: function() {
            switch(this.status) {
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
            switch(this.status) {
                case 'success':
                    return 'success';
                case 'error':
                    return 'error';
                case 'warning':
                    return 'warning';
                case 'info':
                    return 'info';
                default:
                    return 'grey-darken-1';
            }
        },
    },

    created() {
    },
}

</script>