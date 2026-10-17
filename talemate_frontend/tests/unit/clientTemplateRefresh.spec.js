// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, h, nextTick, reactive } from 'vue';
import AppSettingsClients from '@/components/AppSettingsClients.vue';
import ClientConfigEditor from '@/components/ClientConfigEditor.vue';

const mounted = [];
afterEach(() => {
    for (const [app, element, handlers] of mounted.splice(0)) {
        app.unmount();
        expect(handlers.size).toBe(0);
        element.remove();
    }
});

function status(name = 'Local', model = 'first', data = {}) {
    return {
        type: 'client_status', name, message: 'llamacpp', status: 'idle', model_name: model,
        data: {
            template_file: `${model}.jinja2`, prompt_template_example: `preview ${model}`,
            has_prompt_template: true, lock_template: false, api_handles_prompt_template: false,
            reason_response_pattern_default: `${model} strip`, reason_response_pattern_from_template: true,
            reason_validation_pattern_default: `${model} start`, reason_validation_pattern_from_template: true,
            ...data,
        },
    };
}

async function mount(type = 'llamacpp', fields = {}) {
    const config = reactive({ clients: {
        Local: { name: 'Local', type, max_token_length: 16384, lock_template: false, ...fields },
        Other: { name: 'Other', type, max_token_length: 16384, lock_template: false },
    } });
    const handlers = new Set();
    const sent = [];
    const element = document.createElement('div');
    document.body.appendChild(element);
    const editor = { ...ClientConfigEditor, render() {
        return h('div', [h('input', { ref: 'promptTemplateComboBox' }), h('output', JSON.stringify(this.templateInfo))]);
    } };
    const clients = { ...AppSettingsClients, render() {
        return h(editor, { ref: 'editor', client: this.selectedClient, meta: this.selectedMeta,
            config: this.config, status: this.liveStatus[this.selectedName] || null });
    } };
    const app = createApp(clients, { config });
    app.provide('registerMessageHandler', fn => handlers.add(fn));
    app.provide('unregisterMessageHandler', fn => handlers.delete(fn));
    const sockets = [];
    function connect() {
        const socket = new EventTarget();
        socket.readyState = WebSocket.OPEN;
        socket.send = raw => sent.push(JSON.parse(raw));
        socket.addEventListener = vi.fn(socket.addEventListener.bind(socket));
        socket.removeEventListener = vi.fn(socket.removeEventListener.bind(socket));
        sockets.push(socket);
        return socket;
    }
    let socket = connect();
    app.provide('getWebsocket', () => socket);
    async function reconnect() {
        socket.readyState = WebSocket.CLOSED;
        socket.dispatchEvent(new Event('close'));
        socket = connect();
        await nextTick();
    }
    app.provide('getClients', () => [status('Local', 'first', { lock_template: !!fields.lock_template })]);
    app.provide('getAgents', () => []);
    app.provide('navigateToLLMTemplates', vi.fn());
    app.provide('openAgentActionOverrides', vi.fn());
    const page = app.mount(element);
    mounted.push([app, element, handlers]);
    async function receive(message) {
        for (const handler of handlers) handler(message);
        await nextTick();
    }
    await receive({ type: 'config', action: 'client_types', data: { [type]: { requires_prompt_template: true, defaults: {} } } });
    const lastRequest = () => sent.at(-1);
    const complete = async (request = lastRequest(), data = {}) => receive({
        type: 'config', action: 'set_llm_template_complete', request_id: request.request_id,
        data: { ...status('Local', 'manual').data, ...data },
    });
    return { page, config, sent, receive, complete, lastRequest, reconnect, sockets, editor: page.$refs.editor };
}

describe('selected client template status', () => {
    it.each(['openai', 'google'])('%s shows effective reasoning without overwriting the saved toggle', async type => {
        const ctx = await mount(type, { reason_enabled: false, reason_tokens: 8192, effort_level: 'low' });
        expect(ctx.editor.reasonEnabled).toBe(false);
        const saved = JSON.stringify(ctx.config.clients.Local);
        await ctx.receive(status('Local', 'locked-model', { reason_enabled: true, reason_locked: true }));
        expect(ctx.editor.reasonLocked).toBe(true);
        expect(ctx.editor.reasonEnabled).toBe(true);
        ctx.editor.reasonEnabled = false;
        expect(ctx.editor.reasonEnabled).toBe(true);
        expect(JSON.stringify(ctx.config.clients.Local)).toBe(saved);

        await ctx.receive(status('Local', 'unlocked-model', { reason_enabled: false, reason_locked: false }));
        expect(ctx.editor.reasonLocked).toBe(false);
        expect(ctx.editor.reasonEnabled).toBe(false);
        ctx.editor.reasonEnabled = true;
        expect(ctx.config.clients.Local.reason_enabled).toBe(true);
        expect(ctx.config.clients.Local.reason_tokens).toBe(8192);
        expect(ctx.config.clients.Local.effort_level).toBe('low');
    });

    it('gives a zero reasoning budget the 1024 minimum when reasoning is turned on', async () => {
        const ctx = await mount('openai_compat', { reason_enabled: false, reason_tokens: 0 });
        ctx.editor.reasonEnabled = true;
        expect(ctx.config.clients.Local.reason_enabled).toBe(true);
        expect(ctx.config.clients.Local.reason_tokens).toBe(1024);
    });

    it('fills a missing reasoning budget when reasoning is turned on', async () => {
        const ctx = await mount('openai_compat', { reason_enabled: false });
        ctx.editor.reasonEnabled = true;
        expect(ctx.config.clients.Local.reason_tokens).toBe(1024);
    });

    it.each(['llamacpp', 'tabbyapi', 'textgenwebui', 'openai_compat', 'lmstudio', 'koboldcpp', 'ollama'])(
        '%s follows fallback and recovery after a manual template reply without resetting drafts', async type => {
            const ctx = await mount(type);
            ctx.editor.setPromptTemplate('ChatML.jinja2');
            await ctx.complete();
            expect(ctx.editor.templateInfo.template_file).toBe('manual.jinja2');
            ctx.config.clients.Local.max_token_length = 24576;
            ctx.config.clients.Other.reason_tokens = 777;
            ctx.editor.nameDraft = 'unfinished rename';
            ctx.editor.openPanels = ['general', 'reasoning'];
            const draft = JSON.stringify(ctx.config);
            const fallback = type === 'koboldcpp' ? 'KoboldAI.jinja2' : 'default.jinja2';
            await ctx.receive(status('Local', 'missing', { template_file: fallback, has_prompt_template: false, prompt_template_example: 'default preview' }));
            expect(ctx.editor.templateInfo).toMatchObject({ template_file: fallback, has_prompt_template: false, prompt_template_example: 'default preview', reason_response_pattern_default: 'missing strip' });
            await ctx.receive(status('Local', 'recovery'));
            expect(ctx.editor.templateInfo).toMatchObject(status('Local', 'recovery').data);
            expect(ctx.page.selectedName).toBe('Local');
            expect(ctx.editor.nameDraft).toBe('unfinished rename');
            expect(ctx.editor.openPanels).toEqual(['general', 'reasoning']);
            expect(JSON.stringify(ctx.config)).toBe(draft);
        },
    );

    it('adopts updated template content and warning for the same model', async () => {
        const ctx = await mount();
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        await ctx.complete();
        await ctx.receive(status('Local', 'first', { template_file: 'default.jinja2', has_prompt_template: false }));
        expect(ctx.editor.templateInfo.has_prompt_template).toBe(false);
        await ctx.receive(status('Local', 'first', { prompt_template_example: 'updated content' }));
        expect(ctx.editor.templateInfo.prompt_template_example).toBe('updated content');
        expect(ctx.editor.templateInfo.has_prompt_template).toBe(true);
    });

    it('accepts the first status after an unsaved client becomes live', async () => {
        const ctx = await mount();
        ctx.page.setSelection('Other');
        await nextTick();
        expect(ctx.editor.status).toBeNull();
        await ctx.receive(status('Other', 'second'));
        expect(ctx.editor.templateInfo.template_file).toBe('second.jinja2');
    });

    it('does not let another client status or a late template reply contaminate selection', async () => {
        const ctx = await mount();
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        const request = ctx.lastRequest();
        await ctx.receive(status('Other', 'second'));
        ctx.page.setSelection('Other');
        await nextTick();
        await ctx.complete(request);
        expect(ctx.editor.templateInfo.template_file).toBe('second.jinja2');
        ctx.page.setSelection('Local');
        await nextTick();
        await ctx.complete(request);
        expect(ctx.editor.templateInfo.template_file).toBe('first.jinja2');
    });

    it('ignores a reply for the model that was replaced while the request was pending', async () => {
        const ctx = await mount();
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        const request = ctx.lastRequest();
        await ctx.receive(status('Local', 'second'));
        await ctx.complete(request);
        expect(ctx.editor.templateInfo.template_file).toBe('second.jinja2');
    });

    it('ignores unsolicited and superseded replies but accepts the current request', async () => {
        const ctx = await mount();
        await ctx.complete({ data: {} });
        expect(ctx.editor.templateInfo.template_file).toBe('first.jinja2');
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        const old = ctx.lastRequest();
        ctx.editor.setPromptTemplate('Alpaca.jinja2');
        const current = ctx.lastRequest();
        expect(current.request_id).not.toBe(old.request_id);
        await ctx.complete(old);
        expect(ctx.editor.templateInfo.template_file).toBe('Alpaca.jinja2');
        await ctx.complete(current);
        expect(ctx.editor.templateInfo.template_file).toBe('manual.jinja2');
    });

    it('keeps a pending manual choice through status until its reply arrives', async () => {
        const ctx = await mount();
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        await ctx.receive(status());
        expect(ctx.editor.templateInfo.template_file).toBe('ChatML.jinja2');
        await ctx.complete();
        await ctx.receive(status('Local', 'first', { template_file: 'first.jinja2', prompt_template_example: 'manual on backend' }));
        expect(ctx.editor.templateInfo.prompt_template_example).toBe('manual on backend');
    });

    it.each([false, true])('retires a lost reply on same-client/model reconnect (prior completion: %s)', async priorCompletion => {
        const ctx = await mount();
        if (priorCompletion) {
            ctx.editor.setPromptTemplate('Alpaca.jinja2');
            await ctx.complete();
        }
        ctx.config.clients.Local.max_token_length = 24576;
        ctx.config.clients.Other.reason_tokens = 777;
        ctx.editor.nameDraft = 'unfinished rename';
        ctx.editor.openPanels = ['general', 'reasoning'];
        const draft = JSON.stringify(ctx.config);
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        const lost = ctx.lastRequest();
        await ctx.reconnect();
        expect(ctx.editor.pendingTemplateRequest).toBeNull();
        expect(ctx.editor.templateState).toEqual({});
        await ctx.receive(status('Local', 'first', { template_file: 'default.jinja2', has_prompt_template: false, prompt_template_example: 'fallback' }));
        await ctx.complete(lost);
        expect(ctx.editor.templateInfo).toMatchObject({ template_file: 'default.jinja2', has_prompt_template: false, prompt_template_example: 'fallback' });
        ctx.editor.setPromptTemplate('Alpaca.jinja2');
        const current = ctx.lastRequest();
        await ctx.complete(lost);
        expect(ctx.editor.pendingTemplateRequest.id).toBe(current.request_id);
        await ctx.complete(current);
        await ctx.receive(status('Local', 'first', { prompt_template_example: 'recovered' }));
        expect(ctx.editor.templateInfo.prompt_template_example).toBe('recovered');
        expect(ctx.page.selectedName).toBe('Local');
        expect(JSON.stringify(ctx.config)).toBe(draft);
        expect(ctx.editor.nameDraft).toBe('unfinished rename');
        expect(ctx.editor.openPanels).toEqual(['general', 'reasoning']);
        expect(ctx.sockets[0].removeEventListener).toHaveBeenCalledWith('close', expect.any(Function));
    });

    it('releases an interrupted unlock determination without discarding the lock draft', async () => {
        const ctx = await mount('llamacpp', { lock_template: true });
        ctx.editor.lockTemplateChanged(false);
        const lost = ctx.lastRequest();
        await ctx.reconnect();
        expect(ctx.editor.pendingTemplateRequest).toBeNull();
        expect(ctx.editor.waitingForTemplateSelection).toBe(false);
        expect(ctx.editor.templateState).toEqual({});
        await ctx.receive(status('Local', 'first', { lock_template: true, template_file: 'Local__LOCK.jinja2' }));
        await ctx.complete(lost);
        expect(ctx.editor.templateInfo.template_file).toBe('Local__LOCK.jinja2');
        expect(ctx.config.clients.Local.lock_template).toBe(false);
    });

    it('rejects replies and new requests once the socket starts closing', async () => {
        const ctx = await mount();
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        const lost = ctx.lastRequest();
        ctx.sockets[0].readyState = WebSocket.CLOSING;
        await ctx.complete(lost);
        expect(ctx.editor.templateInfo.template_file).toBe('ChatML.jinja2');
        const count = ctx.sent.length;
        ctx.editor.determineBestTemplate();
        expect(ctx.sent).toHaveLength(count);
        expect(ctx.editor.pendingTemplateRequest).toBeNull();
        expect(ctx.editor.templateState).toEqual({});
    });

    it('removes the pending close listener when the editor unmounts', async () => {
        const ctx = await mount();
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        const pending = ctx.editor.pendingTemplateRequest;
        const [app, element, handlers] = mounted.pop();
        app.unmount();
        expect(handlers.size).toBe(0);
        expect(ctx.sockets[0].removeEventListener).toHaveBeenCalledWith('close', pending.onClose);
        element.remove();
    });

    it('preserves a completed unsaved-lock preview across reconnect', async () => {
        const ctx = await mount();
        ctx.editor.lockTemplateChanged(true);
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        await ctx.complete(undefined, { template_file: 'Local__LOCK.jinja2', prompt_template_example: 'draft lock' });
        await ctx.reconnect();
        await ctx.receive(status());
        expect(ctx.editor.templateInfo).toMatchObject({ template_file: 'Local__LOCK.jinja2', prompt_template_example: 'draft lock' });
        expect(ctx.config.clients.Local.lock_template).toBe(true);
    });

    it('preserves an unsaved locked selection across model updates until the lock is applied', async () => {
        const ctx = await mount();
        ctx.editor.lockTemplateChanged(true);
        await ctx.receive(status());
        expect(ctx.editor.waitingForTemplateSelection).toBe(true);
        expect(ctx.editor.templateInfo.template_file).toBeNull();
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        expect(ctx.lastRequest().data.client_name).toBe('Local');
        await ctx.complete(undefined, { template_file: 'Local__LOCK.jinja2' });
        await ctx.receive(status('Local', 'second'));
        expect(ctx.editor.templateInfo.template_file).toBe('Local__LOCK.jinja2');
        expect(ctx.config.clients.Local.lock_template).toBe(true);
        await ctx.receive(status('Local', 'second', { lock_template: true, template_file: 'Local__LOCK.jinja2', prompt_template_example: 'locked current preview' }));
        expect(ctx.editor.templateInfo.prompt_template_example).toBe('locked current preview');
    });

    it('preserves a saved lock and follows its current preview on a model update', async () => {
        const ctx = await mount('llamacpp', { lock_template: true });
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        await ctx.complete(undefined, { template_file: 'Local__LOCK.jinja2' });
        await ctx.receive(status('Local', 'second', { lock_template: true, template_file: 'Local__LOCK.jinja2', prompt_template_example: 'new locked preview' }));
        expect(ctx.editor.templateInfo.prompt_template_example).toBe('new locked preview');
        expect(ctx.config.clients.Local.lock_template).toBe(true);
    });

    it('retains an unsaved unlock preview until runtime adopts it', async () => {
        const ctx = await mount('llamacpp', { lock_template: true });
        ctx.editor.lockTemplateChanged(false);
        expect(ctx.lastRequest().action).toBe('determine_llm_template');
        expect(ctx.lastRequest().data.client_name).toBeNull();
        await ctx.complete(undefined, { template_file: 'first.jinja2' });
        await ctx.receive(status('Local', 'first', { lock_template: true, template_file: 'Local__LOCK.jinja2' }));
        expect(ctx.editor.templateInfo.template_file).toBe('first.jinja2');
        await ctx.receive(status('Local', 'first', { lock_template: false, prompt_template_example: 'unlocked preview' }));
        expect(ctx.editor.templateInfo.prompt_template_example).toBe('unlocked preview');
    });

    it('stops waiting when determination finds no template', async () => {
        const ctx = await mount('llamacpp', { lock_template: true });
        ctx.editor.lockTemplateChanged(false);
        const request = ctx.lastRequest();
        await ctx.receive({ type: 'config', action: 'determine_llm_template_complete', request_id: request.request_id, data: { template: null } });
        expect(ctx.editor.waitingForTemplateSelection).toBe(false);
        expect(ctx.editor.pendingTemplateRequest).toBeNull();
    });

    it('releases a failed request and resumes live updates', async () => {
        const ctx = await mount();
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        const request = ctx.lastRequest();
        await ctx.receive({ type: 'config', action: 'operation_done', request_id: request.request_id, error: { message: 'write failed' } });
        expect(ctx.editor.pendingTemplateRequest).toBeNull();
        await ctx.receive(status('Local', 'first', { prompt_template_example: 'current preview' }));
        expect(ctx.editor.templateInfo.prompt_template_example).toBe('current preview');
    });

    it('keeps editor state when Save replaces the selected draft object', async () => {
        const ctx = await mount();
        ctx.editor.openPanels = ['reasoning'];
        ctx.config.clients.Local = { ...ctx.config.clients.Local };
        await nextTick();
        await ctx.receive(status('Local', 'second'));
        expect(ctx.editor.openPanels).toEqual(['reasoning']);
        expect(ctx.editor.templateInfo.template_file).toBe('second.jinja2');
    });

    it.each(['lock_template', 'api_handles_prompt_template'])('rejects pending replies after draft %s changes', async field => {
        const ctx = await mount();
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        const request = ctx.lastRequest();
        ctx.config.clients.Local[field] = true;
        await nextTick();
        await ctx.complete(request);
        expect(ctx.editor.templateInfo.template_file).toBe('first.jinja2');
        expect(ctx.config.clients.Local[field]).toBe(true);
    });

    it('shows and hides the template picker as the draft toggle changes, before saving', async () => {
        const ctx = await mount('llamacpp', { api_handles_prompt_template: true });
        await ctx.receive(status('Local', 'first', { api_handles_prompt_template: true }));
        expect(ctx.editor.promptTemplateAvailable).toBe(false);
        ctx.config.clients.Local.api_handles_prompt_template = false;
        await nextTick();
        expect(ctx.editor.promptTemplateAvailable).toBe(true);
        ctx.config.clients.Local.api_handles_prompt_template = true;
        await nextTick();
        expect(ctx.editor.promptTemplateAvailable).toBe(false);
    });

    it('chooses a template in the same edit that turns API handles off', async () => {
        const ctx = await mount('llamacpp', { api_handles_prompt_template: true });
        await ctx.receive(status('Local', 'first', { api_handles_prompt_template: true }));
        expect(ctx.editor.promptTemplateAvailable).toBe(false);
        ctx.config.clients.Local.api_handles_prompt_template = false;
        await nextTick();
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        expect(ctx.lastRequest()).toMatchObject({ action: 'set_llm_template', data: { template_file: 'ChatML.jinja2' } });
        await ctx.complete(ctx.lastRequest(), { template_file: 'ChatML.jinja2' });
        expect(ctx.editor.promptTemplateAvailable).toBe(true);
        expect(ctx.editor.templateInfo.template_file).toBe('ChatML.jinja2');
        await ctx.receive(status('Local', 'first', { api_handles_prompt_template: true, template_file: 'ChatML.jinja2' }));
        expect(ctx.editor.promptTemplateAvailable).toBe(true);
        expect(ctx.editor.templateInfo.template_file).toBe('ChatML.jinja2');
        expect(ctx.config.clients.Local.api_handles_prompt_template).toBe(false);
    });

    it('shows the status template again after a plain status refresh', async () => {
        const ctx = await mount();
        ctx.editor.setPromptTemplate('ChatML.jinja2');
        await ctx.complete();
        await ctx.receive(status('Local', 'second'));
        expect(ctx.editor.promptTemplateAvailable).toBe(true);
        expect(ctx.editor.templateInfo.template_file).toBe('second.jinja2');
    });
});
