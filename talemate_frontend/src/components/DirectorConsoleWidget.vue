<template>
    <div class="director-console-widget">
        <v-tooltip text="Director Console" location="top">
            <template v-slot:activator="{ props }">
                <v-app-bar-nav-icon v-if="sceneActive" @click="openDirectorConsole()" v-bind="props" class="bullhorn-icon">
                    <v-icon :color="showMessage ? 'highlight5' : undefined">mdi-bullhorn</v-icon>
                </v-app-bar-nav-icon>
            </template>
        </v-tooltip>
        
        <transition 
            enter-active-class="message-enter-active" 
            leave-active-class="message-leave-active"
            enter-from-class="message-enter-from"
            leave-to-class="message-leave-to">
            <div v-if="showMessage && latestMessage" class="chip-container">
                <v-chip
                    v-if="!latestMessage.character"
                    class="message-chip"
                    color="info"
                    size="small"
                    prepend-icon="mdi-brain"
                >
                    Scene Action
                </v-chip>
                <v-chip
                    v-else
                    class="message-chip"
                    color="director"
                    size="small"
                    prepend-icon="mdi-bullhorn"
                >
                    {{ latestMessage.character }}
                </v-chip>
            </div>
        </transition>
    </div>
</template>

<script>
export default {
    name: 'DirectorConsoleWidget',
    props: {
        sceneActive: {
            type: Boolean,
            required: true
        }
    },
    inject: [
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    data() {
        return {
            latestMessage: null,
            showMessage: false,
            messageTimeout: null,
            pendingMessageUpdate: null
        };
    },
    emits: ['openDirectorConsole'],
    methods: {
        openDirectorConsole() {
            this.$emit('openDirectorConsole');
        },
        handleMessage(message) {
            if (message.type !== "director") {
                return;
            }
            
            if (message.character && !message.message) {
                // Empty instruction (passing turn)
                return;
            }
            
            // Store the latest message
            this.latestMessage = message;
            
            // Clear any existing scheduled update
            if (this.pendingMessageUpdate) {
                clearTimeout(this.pendingMessageUpdate);
            }
            
            // Debounce message updates - wait 100ms to see if more messages arrive
            this.pendingMessageUpdate = setTimeout(() => {
                // Clear any existing display timeout
                if (this.messageTimeout) {
                    clearTimeout(this.messageTimeout);
                }
                
                // Show the message
                this.showMessage = true;
                
                // Set timeout to hide message after 5 seconds
                this.messageTimeout = setTimeout(() => {
                    this.showMessage = false;
                }, 5000);
                
                this.pendingMessageUpdate = null;
            }, 100);
        },
        truncateMessage(message) {
            // Limit message length to prevent overflow
            if (message.length > 100) {
                return message.substring(0, 100) + '...';
            }
            return message;
        }
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        if (this.messageTimeout) {
            clearTimeout(this.messageTimeout);
        }
        if (this.pendingMessageUpdate) {
            clearTimeout(this.pendingMessageUpdate);
        }
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>

<style scoped>
.director-console-widget {
    position: relative;
    display: inline-flex;
    align-items: center;
}

.bullhorn-icon {
    position: relative;
    z-index: 1001; /* Keep icon above the popup */
}

.chip-container {
    position: absolute;
    top: 50%;
    right: 100%;
    transform: translateY(-50%);
    z-index: 1000;
    margin-right: 8px;
}

.message-chip {
    white-space: nowrap;
}

/* Custom transition classes */
.message-enter-active, .message-leave-active {
    transition: opacity 0.3s, transform 0.3s;
}

.message-enter-from {
    opacity: 0;
    transform: translateY(-50%) translateX(40px);
}

.message-leave-to {
    opacity: 0;
    transform: translateY(-50%) translateX(40px);
}
</style>