<template>
    <div class="director-console-widget">
        <v-app-bar-nav-icon v-if="sceneActive" @click="openDirectorConsole()" class="bullhorn-icon">
            <v-icon>mdi-bullhorn</v-icon>
        </v-app-bar-nav-icon>
        
        <transition 
            enter-active-class="message-enter-active" 
            leave-active-class="message-leave-active"
            enter-from-class="message-enter-from"
            leave-to-class="message-leave-to">
            <div v-if="showMessage && latestMessage" class="message-popup">
                <!-- Message title -->
                <div class="message-title">
                    <strong v-if="!latestMessage.character" class="text-info">Director</strong>
                    <strong v-else class="text-secondary">Instruction for {{ latestMessage.character }}</strong>
                </div>
                
                <!-- System message -->
                <div v-if="!latestMessage.character" class="system-message">
                    <v-chip color="info" size="x-small" class="mr-1"><v-icon size="small">mdi-brain</v-icon></v-chip>
                    <span class="message-text text-caption">{{ latestMessage.message }}</span>
                </div>
                
                <!-- Character instruction -->
                <div v-else class="character-instruction">
                    <v-chip color="secondary" size="x-small" class="mr-1"><v-icon size="small">mdi-bullhorn</v-icon></v-chip>
                    <span v-if="latestMessage.message" class="message-text text-caption">
                        {{ latestMessage.message }}
                    </span>
                </div>
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

.message-popup {
    position: absolute;
    top: 50%;
    right: 100%;
    transform: translateY(-50%);
    z-index: 1000;
    border-radius: 4px;
    padding: 6px 12px;
    margin-right: 8px;
    min-width: 400px;
    max-width: 600px;
    transform-origin: right center;
    /* Let Vuetify handle the coloring */
    background: var(--v-theme-surface);
}

.message-title {
    margin-bottom: 2px;
    font-size: 0.75rem;
    line-height: 1;
}

.system-message, .character-instruction {
    display: flex;
    align-items: center;
    width: 100%;
}

.message-text {
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-left: 6px;
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