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