<template>
    <div class="message-container" ref="messageContainer" style="flex-grow: 1; overflow-y: auto;">
        <div v-for="(message, index) in messages" :key="index">
            <div v-if="message.type === 'character' || message.type === 'processing_input'"
                :class="`message ${message.type}`" :id="`message-${message.id}`" :style="{ borderColor: message.color }">
                <div class="character-message">
                    <CharacterMessage :character="message.character" :text="message.text" :color="message.color" :message_id="message.id" />
                </div>
            </div>
            <div v-else-if="message.type === 'request_input' && message.choices">
                <v-alert variant="tonal" type="info"  class="system-message mb-3">
                    {{ message.text }}
                </v-alert>
                <div>
                    <v-radio-group inline class="radio-group" v-if="!message.multiSelect" v-model="message.selectedChoices" :disabled="message.sent">
                        <div v-for="(choice, index) in message.choices" :key="index">
                            <v-radio :key="index" :label="choice" :value="choice"></v-radio>
                        </div>
                    </v-radio-group>
                    <div v-else  class="choice-buttons">
                        <div v-for="(choice, index) in message.choices" :key="index">
                            <v-checkbox :label="choice" v-model="message.selectedChoices" :value="choice" :disabled="message.sent"></v-checkbox>
                        </div>
                    </div>
                    <div class="mb-3">
                        <v-btn v-if="!message.sent" @click="sendAllChoices(message)" color="secondary" :disabled="message.sent">Continue</v-btn>
                    </div>
                </div>
            </div>
            <v-alert v-else-if="message.type === 'system'" variant="text" closable :type="message.status || 'info'" class="system-message mb-3 text-caption"
                :text="message.text">
            </v-alert>
            <div v-else-if="message.type === 'status'" :class="`message ${message.type}`">
                <div class="narrator-message">
                    <StatusMessage :text="message.text" :status="message.status" />
                </div>
            </div>
            <div v-else-if="message.type === 'narrator'" :class="`message ${message.type}`">
                <div class="narrator-message"  :id="`message-${message.id}`">
                    <NarratorMessage :text="message.text" :message_id="message.id" />
                </div>
            </div>
            <div v-else-if="message.type === 'director'" :class="`message ${message.type}`">
                <div class="director-message"  :id="`message-${message.id}`">
                    <DirectorMessage :text="message.text" :message_id="message.id" :character="message.character" :direction_mode="message.direction_mode" :action="message.action"/>
                </div>
            </div>
            <div v-else-if="message.type === 'time'" :class="`message ${message.type}`">
                <div class="time-message"  :id="`message-${message.id}`">
                    <TimePassageMessage :text="message.text" :message_id="message.id" :ts="message.ts" />
                </div>
            </div>

            <div v-else :class="`message ${message.type}`">
                {{ message.text }}
            </div>
        </div>
    </div>
</template>

<script>
import CharacterMessage from './CharacterMessage.vue';
import NarratorMessage from './NarratorMessage.vue';
import DirectorMessage from './DirectorMessage.vue';
import TimePassageMessage from './TimePassageMessage.vue';
import StatusMessage from './StatusMessage.vue';

const MESSAGE_FLAGS = {
    NONE: 0,
    HIDDEN: 1,
}

export default {
    name: 'SceneMessages',
    components: {
        CharacterMessage,
        NarratorMessage,
        DirectorMessage,
        TimePassageMessage,
        StatusMessage,
    },
    data() {
        return {
            messages: [],
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput'],
    provide() {
        return {
            requestDeleteMessage: this.requestDeleteMessage,
            createPin: this.createPin,
            fixMessageContinuityErrors: this.fixMessageContinuityErrors,
        }
    },
    methods: {

        createPin(message_id){
            this.getWebsocket().send(JSON.stringify({ type: 'interact', text:'!ws_sap:'+message_id}));
        },

        fixMessageContinuityErrors(message_id) {
            this.getWebsocket().send(JSON.stringify({ type: 'interact', text:'!fixmsg_ce:'+message_id}));
        },

        requestDeleteMessage(message_id) {
            this.getWebsocket().send(JSON.stringify({ type: 'delete_message', id: message_id }));
        },

        handleChoiceInput(data) {
            // Create a new message with buttons for the choices
            const message = {
                id: data.id,
                type: data.type,
                text: data.message,
                choices: data.data.choices,
                selectedChoices: data.data.default || (data.data.multi_select ? [] : null),
                multiSelect: data.data.multi_select,
                color: data.color,
                sent: false,
                ts: data.ts,
            };
            this.messages.push(message);
        },

        sendChoice(message, choice) {
            const index = message.selectedChoices.indexOf(choice);
            if (index === -1) {
                // If the checkbox is checked, add the choice to the selectedChoices array
                message.selectedChoices.push(choice);
            } else {
                // If the checkbox is unchecked, remove the choice from the selectedChoices array
                message.selectedChoices.splice(index, 1);
            }
        },

        sendAllChoices(message) {

            let text;

            if(message.multiSelect) {
                text = message.selectedChoices.join(', ');
            } else {
                text = message.selectedChoices;
            }

            // Send all selected choices to the server
            this.getWebsocket().send(JSON.stringify({ type: 'interact', text: text }));
            // Clear the selectedChoices array
            message.sent = true;
            this.setWaitingForInput(false);
        },

        messageTypeIsSceneMessage(type) {
            return ![ 
                'request_input', 
                'client_status', 
                'agent_status', 
                'status', 
                'autocomplete_suggestion' 
            ].includes(type);
        },

        handleMessage(data) {

            var i;

            if (data.type == "clear_screen") {
                this.messages = [];
            }

            if (data.type == "remove_message") {

                // find message where type == "character" and id == data.id
                // remove that message from the array
                let newMessages = [];
                for (i = 0; i < this.messages.length; i++) {
                    if (this.messages[i].id != data.id) {
                        newMessages.push(this.messages[i]);
                    }
                }
                this.messages = newMessages;

                return
            }

            if (data.type == "message_edited") {

                // find the message by id and update the text#

                for (i = 0; i < this.messages.length; i++) {
                    if (this.messages[i].id == data.id) {
                        console.log("message_edited!", i , data.id, data.message, this.messages[i].type, data)
                        if (this.messages[i].type == "character") {
                            this.messages[i].text = data.message.split(':')[1].trim();
                        } else {
                            this.messages[i].text = data.message;
                        }
                        break;
                    }
                }

                return
            }
            
            if (data.message) {

                if(data.flags && data.flags & MESSAGE_FLAGS.HIDDEN) {
                    return;
                }

                if (data.type === 'character') {
                    const parts = data.message.split(':');
                    const character = parts.shift();
                    const text = parts.join(':');
                    this.messages.push({ id: data.id, type: data.type, character: character.trim(), text: text.trim(), color: data.color }); // Add color property to the message
                } else if (data.type === 'director') {
                    this.messages.push(
                        { 
                            id: data.id, 
                            type: data.type, 
                            character: data.character, 
                            text: data.message, direction_mode: data.direction_mode,
                            action: data.action
                        }
                    );
                } else if (this.messageTypeIsSceneMessage(data.type)) {
                    this.messages.push({ id: data.id, type: data.type, text: data.message, color: data.color, character: data.character, status:data.status, ts:data.ts }); // Add color property to the message
                } else if (data.type === 'status' && data.data && data.data.as_scene_message === true) {

                    // status message can only exist once, remove the most recent one (if within the last 100 messages)
                    // by walking the array backwards then removing the first one found
                    // then add the new status message
                    let max = 100;
                    let iter = 0;
                    for (i = this.messages.length - 1; i >= 0; i--) {
                        if (this.messages[i].type == 'status') {
                            this.messages.splice(i, 1);
                            break;
                        }
                        iter++;
                        if(iter > max) {
                            break;
                        }
                    }

                    this.messages.push({
                         id: data.id, 
                         type: data.type,
                         text: data.message, 
                         status: data.status, 
                         ts: data.ts
                    });
                }
            }


        }
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>

<style scoped>
.message-container {
    overflow-y: auto;
}

.message {
    padding: 10px;
    white-space: pre-wrap;
    margin-bottom: 10px;
}

.message.system {
    color: #FFA726;
}

.message.narrator {
    color: #26A69A;
}

.message.character {
    color: #E0E0E0;
}

.character-message {
    display: flex;
    flex-direction: row;
}

.character-name {
    font-weight: bold;
    margin-right: 10px;
}

.character-avatar {
    height: 50px;
    margin-top: 10px;
}

.hotbuttons-section {
    display: flex;
    justify-content: flex-start;
    margin-bottom: 10px;
}

.hotbuttons-section-1,
.hotbuttons-section-2,
.hotbuttons-section-3 {
    display: flex;
    align-items: center;
    margin-right: 20px;
}

.choice-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}

.message.request_input {}
</style>