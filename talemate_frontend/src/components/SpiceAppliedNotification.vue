<template>
    <v-snackbar color="grey-darken-4" location="top" v-model="spiceApplied" :timeout="5000" max-width="400" multi-line>
        <div class="text-caption text-highlight4">
            <v-icon color="highlight4">mdi-chili-mild</v-icon>
            Spice applied!
        </div>
        {{ spiceAppliedDetail }}
    </v-snackbar>
</template>

<script>

export default {
    name: 'SpiceAppliedNotification',
    props: {
        uids: {
            type: Array,
            required: true
        }
    },
    data() {
        return {
            spiceApplied: false,
            spiceAppliedDetail: ''
        }
    },
    inject: [
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    methods: {
        handleMessage(message) {
            if (message.type === 'spice_applied' && this.uids.includes(message.data.uid)) {
                if(message.data.context[1])
                    this.spiceAppliedDetail = `${message.data.context[1]}: ${message.data.spice}`;
                else
                    this.spiceAppliedDetail = `${message.data.spice}`;
                this.spiceApplied = true;
            } else if (message.type !== 'world_state_manager') {
                return;
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>