<template>
    <v-card class="mb-2">
        <v-card-text>
            <!-- System message (non-character message) -->
            <div v-if="!message.character" class="system-message">
                <v-chip color="info" size="small" class="mr-2 mb-1"><v-icon>mdi-brain</v-icon></v-chip>
                <span class="text-body-2">{{ message.message }}</span>
                <div v-if="message.action && message.action !== 'actor_instruction'" class="text-caption text-muted mt-1">
                    {{ message.action }}
                </div>
            </div>
            
            <!-- Character instruction -->
            <div v-else class="character-instruction">
                <v-chip color="secondary" size="small" class="mr-2 mb-1"><v-icon>mdi-bullhorn</v-icon></v-chip>
                <span v-if="message.message">
                    <span class="text-body-2">Instruct {{ message.character }}</span>
                    <div>
                        <span class="text-caption text-muted">{{ message.message }}</span>
                    </div>
                </span>
            </div>
        </v-card-text>
    </v-card>
</template>

<script>
export default {
    name: 'DirectorConsoleMessage',
    props: {
        message: {
            type: Object,
            required: true
        }
    }
}
</script>

<style scoped>
.system-message, .character-instruction {
    white-space: pre-wrap;
}
</style>