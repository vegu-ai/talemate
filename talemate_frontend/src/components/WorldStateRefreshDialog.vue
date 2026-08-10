<template>
    <RequestInput ref="input" title="Update World Snapshot"
        :instructions="'Optionally provide instructions for the world state update.'"
        input-type="multiline" icon="mdi-refresh" :size="750" :required="false"
        checkbox-label="Wipe and start fresh"
        checkbox-hint="Discard the current snapshot instead of updating it"
        placeholder="Focus on what the characters are carrying." @continue="apply" />
</template>

<script>
import RequestInput from './RequestInput.vue';
import { isPrimaryModifier } from '@/utils/keyboardModifiers';

export default {
    name: 'WorldStateRefreshDialog',
    components: {
        RequestInput,
    },
    inject: ['getWebsocket'],
    methods: {
        handleClick(event) {
            if (!!event && isPrimaryModifier(event)) {
                this.open();
                return;
            }
            this.send(false, "");
        },

        open() {
            this.$nextTick(() => {
                this.$refs.input.openDialog();
            });
        },

        apply(input, params) {
            this.send(!!params.checked, input || "");
        },

        send(reset, instructions) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_agent',
                action: 'request_update',
                reset,
                instructions,
            }));
        },
    },
}
</script>
