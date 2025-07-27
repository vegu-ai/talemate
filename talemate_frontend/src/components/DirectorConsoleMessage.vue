<template>
    <v-card class="mb-2">
        <v-card-text>
            <!-- System message (non-character message) -->
            <div v-if="!message.character" class="system-message">
                <v-chip 
                    :color="message.subtype === 'function_call' ? 'orange' : 'info'" 
                    size="small" 
                    class="mr-2 mb-1"
                >
                    <v-icon>{{ message.subtype === 'function_call' ? 'mdi-function-variant' : 'mdi-brain' }}</v-icon>
                </v-chip>
                
                <!-- Function call display -->
                <span v-if="message.subtype === 'function_call'" class="function-call">
                    <span class="text-body-2">{{ message.message }}</span>
                    <div v-if="message.data && message.data.function_call && message.data.function_call.arguments" class="mt-1">
                        <div v-for="(value, key) in message.data.function_call.arguments" :key="key" class="text-caption text-muted">
                            <strong>{{ key }}:</strong> {{ typeof value === 'object' ? JSON.stringify(value) : value }}
                        </div>
                    </div>
                </span>
                
                <!-- Regular system message -->
                <span v-else class="text-body-2">{{ message.message }}</span>
                <div v-if="message.action && message.action !== 'actor_instruction' && message.subtype !== 'function_call'" class="text-caption text-muted mt-1">
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