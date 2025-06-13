<template>
    <v-chip v-if="requestInformation && (!requestInformation.end_time || requestInformation.age < 3)" :color="color" label size="x-small" variant="text" class="ml-1" prepend-icon="mdi-progress-download">{{ formattedRate }} t/s</v-chip>
</template>

<script>
export default {
    props: {
        requestInformation: {
            type: Object,
            required: true
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