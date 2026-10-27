<template>
    <RequestInput ref="input" title="Save Scene" instructions="Enter a name for the scene save"
        input-type="text" icon="mdi-content-save-all" :size="750"
        :close-on-continue="false" :loading="!!pending?.requestId" :error="error"
        @continue="submit" @cancel="cancel" />
</template>

<script>
import RequestInput from './RequestInput.vue';
import { sceneIdentityOf } from '@/utils/sceneAgentOverrides';

let sequence = 0;

export default {
    components: { RequestInput },
    props: { scene: Object },
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
    data() {
        return { pending: null, savedInput: '', inputIdentity: null, error: '' };
    },
    methods: {
        open() {
            if (this.pending) return this.pending.promise;
            const identity = sceneIdentityOf(this.scene);
            if (!identity) return Promise.resolve({ status: 'cancelled' });
            if (identity !== this.inputIdentity) this.savedInput = '';
            this.inputIdentity = identity;
            this.error = '';
            let resolve;
            const promise = new Promise(done => { resolve = done; });
            this.pending = { identity, resolve, promise, requestId: null };
            this.$refs.input.openDialog({ input: this.savedInput });
            return promise;
        },
        finish(result) {
            const pending = this.pending;
            this.pending = null;
            this.$refs.input.answered = true;
            this.$refs.input.open = false;
            if (pending) pending.resolve(result);
        },
        cancel() {
            if (this.pending?.requestId) return;
            this.savedInput = this.$refs.input.input;
            this.finish({ status: 'cancelled' });
        },
        submit(name) {
            const pending = this.pending;
            if (!pending || pending.requestId) return;
            this.savedInput = name;
            this.error = '';
            if (sceneIdentityOf(this.scene) !== pending.identity) {
                this.finish({ status: 'cancelled' });
                return;
            }
            pending.requestId = `scene-save-${Date.now().toString(36)}-${++sequence}`;
            try {
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager', action: 'save_scene',
                    save_as: name, project_name: this.scene.data.project_name || this.scene.name,
                    scene_identity: pending.identity, request_id: pending.requestId,
                }));
            } catch (error) {
                pending.requestId = null;
                this.error = error.message;
            }
        },
        reset() {
            this.finish({ status: 'cancelled' });
            this.savedInput = '';
            this.inputIdentity = null;
            this.error = '';
        },
        handleMessage(data) {
            if (data.type === 'system' && ['scene.loading', 'scene.loaded', 'scene.closed', 'scene.load_failure'].includes(data.id)) {
                this.reset();
                return;
            }
            const pending = this.pending;
            if (!pending) return;
            if (data.type === 'scene_status' && String(data.data?.id) !== pending.identity) {
                this.reset();
                return;
            }
            if (data.type !== 'world_state_manager' || !pending.requestId || data.request_id !== pending.requestId) return;
            if (data.action === 'scene_saved' && data.scene_identity === pending.identity) {
                this.finish({ status: 'saved', identity: pending.identity });
            } else if (data.action === 'operation_done' && data.error) {
                pending.requestId = null;
                this.error = data.error.message;
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    beforeUnmount() {
        this.unregisterMessageHandler(this.handleMessage);
        this.finish({ status: 'cancelled' });
    },
};
</script>
