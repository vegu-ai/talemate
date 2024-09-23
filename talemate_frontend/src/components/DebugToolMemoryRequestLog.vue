<template>

    <v-card class="ma-4">
        <v-card-text class="text-muted text-caption">
            Inspect the requests for memory retrieval.
        </v-card-text>
    </v-card>

    <v-list-item density="compact">
        <v-list-item-title>
            <v-chip size="x-small" color="primary">Max. {{ max_memory_requests }}</v-chip>
            <v-btn color="delete" class="ml-2" variant="text" size="small" @click="clearMemoryRequests" prepend-icon="mdi-close">Clear</v-btn>
            <v-slider density="compact" v-model="max_memory_requests" min="1" hide-details max="250" step="1" color="primary"></v-slider>
        </v-list-item-title>
    </v-list-item>

    <v-list-item v-for="(memory_request, index) in memory_requests" :key="index" @click="openMemoryRequestView(index)">

        <div class="ml-2 mr-2 text-muted text-caption font-italic">
        {{ memory_request.query }}
        </div>
        <v-list-item-subtitle>
            <!-- matches or not matches ?-->
            <v-chip size="x-small" class="mr-1" :color="memory_request.success ? 'success' : 'warning'" variant="text" label>{{ memory_request.accepted_results.length+" / "+memory_request.results.length+ " matches"}}</v-chip>
            <!-- closest distance -->
            <v-chip size="x-small" class="mr-1" color="info" variant="text" label>{{ to2Decimals(memory_request.closest_distance) }} - {{ to2Decimals(memory_request.furthest_distance) }}, {{ to2Decimals(memory_request.max_distance) }}
                <v-icon size="14" class="ml-1">mdi-flag-checkered</v-icon>
            </v-chip>
            <!-- duration -->
            <v-chip size="x-small" class="mr-1" color="grey-darken-1" variant="text" label>{{ memory_request.duration }}s<v-icon size="14" class="ml-1">mdi-clock</v-icon></v-chip>
        </v-list-item-subtitle>
        <v-divider class="mt-1" v-if="memory_request.new_agent_activity"></v-divider>
    </v-list-item>

    <DebugToolMemoryRequestView :memory_requests="memory_requests" ref="memory_requestView" />
</template>
<script>

import DebugToolMemoryRequestView from './DebugToolMemoryRequestView.vue';

export default {
    name: 'DebugToolMemoryRequestLog',
    data() {
        return {
            memory_requests: [],
            total: 1,
            max_memory_requests: 50,
        }
    },
    components: {
        DebugToolMemoryRequestView,
    },
    inject: [
        'getWebsocket', 
        'registerMessageHandler',
        'unregisterMessageHandler',
        'setWaitingForInput',
    ],

    methods: {

        to2Decimals(num) {
            return Math.round(num * 100) / 100;
        },

        clearMemoryRequests() {
            this.memory_requests = [];
            this.total = 0;
        },
        handleMessage(data) {

            if(data.type === "system"&& data.id === "scene.loaded") {
                this.memory_requests = [];
                this.total = 0;
                return;
            }

            if(data.type === "memory_request") {

                let memoryRequest = {...data.data}

                console.log({memoryRequest, meta: data.meta})

                memoryRequest.success = memoryRequest.accepted_results.length > 0;
                memoryRequest.agent_stack_uid = data.meta.agent_stack_uid;

                // if data.meta.agent_stack_uid is different from the previous
                // then set new_agent_activity to true
                memoryRequest.new_agent_activity = this.memory_requests.length === 0 || this.memory_requests[0].agent_stack_uid !== data.meta.agent_stack_uid;

                memoryRequest.duration = Math.round(data.meta.duration * 100) / 100;

                this.memory_requests.unshift(memoryRequest)
                while(this.memory_requests.length > this.max_memory_requests) {
                    this.memory_requests.pop();
                }
            }
        },

        openMemoryRequestView(index) {
            this.$refs.memory_requestView.open(index);
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