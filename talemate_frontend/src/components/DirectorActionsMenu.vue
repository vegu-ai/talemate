<template>
    <v-tooltip text="Configure disabled actions" location="top">
        <template v-slot:activator="{ props: tooltipProps }">
            <v-menu
                class="ml-2"
                v-model="menuOpen"
                @update:modelValue="handleMenuToggle"
            >
                <template v-slot:activator="{ props: menuProps }">
                    <v-chip
                        v-bind="Object.assign({}, menuProps, tooltipProps)"
                        size="small"
                        class="ml-2"
                        color="primary"
                        label
                        clickable
                        :disabled="appBusy || !appReady"
                    >
                        <v-icon start>mdi-cog</v-icon>
                        Actions
                        <v-icon end>mdi-chevron-down</v-icon>
                    </v-chip>
                </template>
                <v-list density="compact">
                    <v-list-subheader class="text-caption">
                        <v-icon size="small" class="mr-1">mdi-information-outline</v-icon>
                        Disable actions to prevent the director from using them
                    </v-list-subheader>
                    <v-divider></v-divider>
                    <v-list-item
                        v-for="choice in actionChoices"
                        :key="choice.value"
                        @click="toggleAction(choice.value)"
                        :disabled="lockedActionIds.has(choice.value)"
                    >
                        <template v-slot:prepend>
                            <v-checkbox-btn
                                :model-value="!isActionDisabled(choice.value)"
                                @click.stop="toggleAction(choice.value)"
                                :disabled="lockedActionIds.has(choice.value)"
                                density="compact"
                                color="success"
                                hide-details
                            ></v-checkbox-btn>
                        </template>
                        <v-list-item-title class="text-caption">
                            {{ choice.label }}
                            <span v-if="lockedActionIds.has(choice.value)" class="text-caption text-muted ml-1">(locked)</span>
                        </v-list-item-title>
                    </v-list-item>
                    <v-list-item v-if="actionChoices.length === 0" class="text-caption text-muted">
                        No actions available
                    </v-list-item>
                </v-list>
            </v-menu>
        </template>
    </v-tooltip>
</template>

<script>
export default {
    name: 'DirectorActionsMenu',
    props: {
        mode: {
            type: String,
            required: true,
            validator: (value) => ['chat', 'scene_direction'].includes(value),
        },
        appBusy: {
            type: Boolean,
            default: false,
        },
        appReady: {
            type: Boolean,
            default: true,
        },
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    data() {
        return {
            menuOpen: false,
            actionChoices: [],
            disabledActionIds: [],
            lockedActionIds: new Set(),
        }
    },
    methods: {
        handleMenuToggle(isOpen) {
            // Keep the list fresh: callback descriptors can change when node modules are edited,
            // but the backend only sends updates in response to explicit requests.
            if (isOpen) {
                this.requestSubActionChoices();
                this.requestDisabledSubActions();
            }
        },
        requestSubActionChoices() {
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'get_sub_action_choices',
                mode: this.mode,
            }));
        },
        requestDisabledSubActions() {
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'get_disabled_sub_actions',
                mode: this.mode,
            }));
        },
        isActionDisabled(actionId) {
            return this.disabledActionIds.includes(actionId);
        },
        toggleAction(actionId) {
            // Don't allow toggling locked actions
            if (this.lockedActionIds.has(actionId)) {
                return;
            }
            
            const isCurrentlyDisabled = this.isActionDisabled(actionId);
            let newDisabledList;
            
            if (isCurrentlyDisabled) {
                // Enable it - remove from disabled list
                newDisabledList = this.disabledActionIds.filter(id => id !== actionId);
            } else {
                // Disable it - add to disabled list
                newDisabledList = [...this.disabledActionIds, actionId];
            }
            
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'set_disabled_sub_actions',
                mode: this.mode,
                disabled_action_ids: newDisabledList,
            }));
        },
        handleMessage(message) {
            if (message.type !== 'director') {
                return;
            }
            
            if (message.action === 'sub_action_choices' && message.mode === this.mode) {
                this.actionChoices = message.choices || [];
                // Extract locked action IDs
                this.lockedActionIds = new Set(
                    (message.choices || [])
                        .filter(choice => choice.locked === true)
                        .map(choice => choice.value)
                );
            }
            
            if (message.action === 'disabled_sub_actions' && message.mode === this.mode) {
                this.disabledActionIds = message.disabled_action_ids || [];
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        // Keep initial behavior (menu might be opened immediately after mount)
        this.requestSubActionChoices();
        this.requestDisabledSubActions();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>

<style scoped>
</style>

