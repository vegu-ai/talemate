<template>
    <v-dialog v-model="show" max-width="800">
        <v-card v-if="memory_request !== null">
            <v-card-title>
                Memory Request
                <!-- matches or not matches ?-->
                <v-chip size="x-small" class="mr-1" :color="memory_request.success ? 'success' : 'warning'" variant="text" label>{{ memory_request.accepted_results.length+" / "+memory_request.results.length+ " matches"}}</v-chip>
                <!-- closest distance -->
                <v-chip size="x-small" class="mr-1" color="info" variant="text" label>{{ to2Decimals(memory_request.closest_distance) }} - {{ to2Decimals(memory_request.furthest_distance) }}, {{ to2Decimals(memory_request.max_distance) }}
                    <v-icon size="14" class="ml-1">mdi-flag-checkered</v-icon>
                </v-chip>
                <!-- duration -->
                <v-chip size="x-small" class="mr-1" color="grey-darken-1" variant="text" label>{{ memory_request.duration }}s<v-icon size="14" class="ml-1">mdi-clock</v-icon></v-chip>

                <!-- toggle truncateLongText -->
                <v-chip size="x-small" class="mr-1" color="primary" variant="text" @click="truncateLongText = !truncateLongText" label>
                    Truncate
                    <v-icon size="14" class="ml-1">{{ truncateLongText ? 'mdi-check-circle-outline' : 'mdi-circle-outline' }}</v-icon>
                </v-chip>
            </v-card-title>
                <v-card-text>
                    <div class="font-italic text-muted">
                        {{ truncateText(memory_request.query) }}

                    </div>

                    <v-table>
                    <!--
                    {
        "query": "Elmer: \"Kaira...\" *I say suddenly.* \"How did we first meet? I can't seem to recall, but i feel like the memory is there... i... i just can't grasp it.\"",
        "results": [
            {
                "doc": "Captain Elmer and Kaira first met during their rigorous training for the Infinity Quest mission. Their initial interactions were marked by a sense of mutual respect and curiosity.",
                "distance": 0.34782390420399134,
                "meta": {
                    "character": "__narrator__",
                    "session": "9624b36a-3",
                    "source": "talemate",
                    "ts": "P1M",
                    "typ": "history"
                }
            },
        ],
        "accepted_results": [
            {
                "doc": "11 Months ago: Captain Elmer and Kaira first met during their rigorous training for the Infinity Quest mission. Their initial interactions were marked by a sense of mutual respect and curiosity.",
                "distance": 0.34782390420399134,
                "meta": {
                    "character": "__narrator__",
                    "session": "9624b36a-3",
                    "source": "talemate",
                    "ts": "P1M",
                    "typ": "history"
                }
            },
        ],
        "query_params": {
            "limit": 10
        },
        "closest_distance": 0.34782390420399134,
        "furthest_distance": 0.4819549331888565,
        "max_distance": 1,
        "success": true,
        "agent_stack_uid": "0c571b5a-b664-41d6-9312-31c9d936373a",
        "new_agent_activity": true,
        "duration": 0.08
    }
                    -->
                    <thead>
                        <tr>
                            <th>Doc</th>
                            <th class="text-right">Distance</th>
                        </tr>
                    </thead>

                    <tbody>
                        <tr v-for="(result, index) in memory_request.results" :key="index">
                            <td>
                                <div :class="result.distance <= memory_request.max_distance ? '' : 'text-grey'">
                                    {{ truncateText(result.doc) }}
                                </div>
                                <div>
                                    <v-chip v-for="(meta, key) in result.meta" :key="key" size="x-small" class="mr-1" color="muted" variant="text" label>{{ key }}: {{ meta }}</v-chip>
                                </div>
                            </td>
                            <td class="text-right"><span :class="result.distance <= memory_request.max_distance ? 'text-success': 'text-warning'">{{ to2Decimals(result.distance) }}</span></td>
                        </tr>
    
                    </tbody>

                </v-table>
            </v-card-text>
        </v-card>
    </v-dialog>
</template>
<script>

export default {
    name: 'DebugToolMemoryRequestView',
    props: {
        memory_requests: Object,
    },
    data() {
        return {
            show: false,
            selected: null,
            memory_request: null,
            truncateLongText: true,
        }
    },
    methods: {
        to2Decimals(num) {
            return Math.round(num * 100) / 100;
        },
        open(index) {
            this.select(index);
            this.show = true;
        },
        select(index) {
            this.selected = index;
            this.memory_request = this.memory_requests[index];
        },
        truncateText(text) {
            if(text.length > 255 && this.truncateLongText) {
                return text.substring(0, 255) + "...";
            }
            return text;
        }
    }
}

</script>
<style scoped>
</style>