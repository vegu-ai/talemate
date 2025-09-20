<template>
    <div class="text-caption d-flex align-center">
        <v-progress-circular indeterminate size="14" width="2" class="mr-2"></v-progress-circular>
        {{ label || 'Thinking...' }}
    </div>
</template>

<script>
export default {
    name: 'DirectorConsoleChatMessageLoading',
    props: {
        label: {
            type: String,
            default: null,
        },
    },
}
</script>

<style scoped>
</style>


