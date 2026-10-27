<template>
    <v-alert variant="text" :icon="icon" density="compact">
        <v-alert-title>{{ title }}</v-alert-title>
        <div class="text-medium-emphasis">
            <slot></slot>
        </div>
    </v-alert>
    <v-divider class="mb-2"></v-divider>
</template>

<script>
export default {
    name: 'AppSettingsPageHeader',
    props: {
        title: String,
        icon: String,
    },
}
</script>
