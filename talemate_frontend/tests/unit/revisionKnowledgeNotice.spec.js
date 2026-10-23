// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, reactive } from 'vue';
import Knowledge from '@/components/WorldStateManagerCharacterKnowledge.vue';
import History from '@/components/WorldStateManagerHistory.vue';
let app, host;
afterEach(() => { app?.unmount(); host?.remove(); });
describe('stale knowledge notices', () => {
    for (const [name, component] of [['History', History], ['Knowledge', Knowledge]]) {
        it.each([
            ['perceptions', 'Analyze perceptions'],
            ['facts', 'Refresh facts'],
            ['index_repair', 'Update knowledge'],
        ])(`${name} shows no list banner for a pending %s refresh`, (operation, label) => {
            const scene = reactive({ data: { revision_refreshes: [{ id: 9, archive_ids: [], revision_refresh: {
                required: true, operations: [operation], label,
            } }] } });
            host = document.createElement('div'); document.body.appendChild(host);
            app = createApp(component, { scene, immutableCharacter: { name: 'Mara' } });
            const errors = [];
            app.config.errorHandler = error => errors.push(error);
            app.config.warnHandler = () => {};
            for (const injection of ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'])
                app.provide(injection, injection === 'getWebsocket' ? () => ({ send: vi.fn() }) : vi.fn());
            const container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
            for (const tag of ['VAlert','VCard','VCardText','VCardTitle','VCardActions','VRow','VCol','VTabs','VTab','VWindow','VWindowItem','VSheet','VBtn','VTooltip','VChip']) app.component(tag, container);
            app.mount(host);
            expect(errors).toEqual([]);
            expect(host.textContent).not.toContain('Changed passages');
            expect(host.textContent).not.toContain('Some passages need');
            expect(host.textContent).not.toContain(`Use ${label}`);
        });
    }
});
