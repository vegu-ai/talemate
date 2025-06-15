<template>
    <v-fade-transition>
        <v-chip v-if="requestInformation && (!requestInformation.end_time || requestInformation.age < timeout)" :color="color" label size="x-small" variant="text" class="ml-1" prepend-icon="mdi-progress-download">{{ formattedRate }} t/s</v-chip>
    </v-fade-transition>
</template>

<script>
export default {
    props: {
        requestInformation: {
            type: Object,
            required: false
        }
    },
    data() {
        return {
            timeout: 3
        }
    },
    computed: {
        formattedRate() {
            return this.requestInformation.rate.toFixed(2)
        },
        color() {
            if(this.requestInformation.status === "completed") {
                return "muted"
            }
            if(this.requestInformation.status === "stopped") {
                return "error"
            }
            return "highlight3"
        }
    }
}
</script>