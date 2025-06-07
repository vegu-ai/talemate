<template>
    <v-alert v-if="appBusy" type="primary" variant="tonal">
        Agents are currently busy - please wait for them to finish their current task before installing or uninstalling packages.
        <v-progress-linear color="primary" height="2" indeterminate></v-progress-linear>

    </v-alert>
</template>

<script>
export default {
    name: 'PackageManagerMenu',
    props: {
        scene: {
            type: Object,
            required: true,
        },
        appBusy: {
            type: Boolean,
            default: false,
        },
    }
}
</script>