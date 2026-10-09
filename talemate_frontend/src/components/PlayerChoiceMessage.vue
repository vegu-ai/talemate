<template>
    <v-alert color="muted" variant="text">
        <template v-slot:close>
            <MessageCloseButton label="Dismiss these suggestions" @click="cancel" />
        </template>
        <v-card-title class="text-body-large">
            The
            <span class="text-director text-secondary"><v-icon size="small">mdi-bullhorn</v-icon> Director</span> 
            suggests some actions for <span class="text-primary">{{ character }}</span>

            <v-btn variant="text" size="small" color="secondary" prepend-icon="mdi-refresh" @click="regenerate" :disabled="busy">Regenerate</v-btn>
            <v-btn variant="text" size="small" color="primary" prepend-icon="mdi-cogs" @click="settings" :disabled="busy">Settings</v-btn>
        </v-card-title>

        <p v-if="busy">
            <v-progress-linear color="primary" height="2" indeterminate></v-progress-linear>
        </p>

        <v-list density="compact" :disabled="busy">
            <v-list-item v-for="(choice, index) in choices" :key="index" @click="selectChoice(index)">
                <v-list-item-title>
                    {{ choice }}
                </v-list-item-title>
            </v-list-item>
            <v-list-item @click="cancel" prepend-icon="mdi-cancel">
                <v-list-item-title>Cancel</v-list-item-title>
            </v-list-item>
        </v-list>
    </v-alert>


</template>

<script>
import MessageCloseButton from './MessageCloseButton.vue';

export default {
    name: 'PlayerChoiceMessage',
    components: {
        MessageCloseButton,
    },
    props: {
        choices: Array,
        character: String,
        uxLocked: Boolean,
        isLastMessage: Boolean,
    },
    data() {
        return {
            busy: false,
        }
    },
    watch: {
        choices() {
            this.busy = false;
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput', 'unregisterMessageHandler', 'openAgentSettings'],
    emits: ['close'],
    methods: {
        selectChoice(index) {
            this.$emit('close');
            this.getWebsocket().send(JSON.stringify({
                type: "director",
                action: "select_choice",
                choice: this.choices[index],
                character: this.character,
            }));
        },
        settings() {
            this.openAgentSettings('director', '_generate_choices');
        },
        cancel() {
            this.$emit('close');
        },
        regenerate() {
            this.busy = true;
            this.getWebsocket().send(JSON.stringify({
                type: "director",
                action: "request_dynamic_choices",
                character: this.character,
            }));
        },
    }
}

</script>