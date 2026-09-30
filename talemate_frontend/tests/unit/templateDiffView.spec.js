// @vitest-environment jsdom

import { describe, expect, it } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import TemplateDiffView from '@/components/prompts/TemplateDiffView.vue';

const Container = defineComponent({
    inheritAttrs: false,
    setup: (_, { slots }) => () => h('div', [slots.activator?.({ props: {} }), slots.default?.()]),
});

function mount(props) {
    const emitted = [];
    const app = createApp({
        render: () => h(TemplateDiffView, {
            ref: 'diff',
            modelValue: true,
            uid: 'summarizer.summarize-dialogue',
            group: 'user',
            onApply: content => emitted.push(content),
            ...props,
        }),
    });
    for (const name of ['VDialog', 'VCard', 'VCardTitle', 'VCardText', 'VCardActions', 'VIcon', 'VChip', 'VSpacer', 'VDivider', 'VBtn', 'VTooltip']) {
        app.component(name, Container);
    }
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = app.mount(host);
    return { app, host, diff: () => root.$refs.diff, emitted };
}

describe('TemplateDiffView', () => {
    it('shows the override beside the default and applies a copied change', async () => {
        const { app, host, diff, emitted } = mount({
            overrideContent: 'intro\nSummarize.\n',
            defaultContent: 'intro\n{% include "audience-summary-instructions.jinja2" %}\nSummarize.\n',
        });
        try {
            await nextTick();
            await nextTick();
            const view = diff().view;
            expect(host.querySelector('.cm-mergeView')).not.toBeNull();
            expect(view.b.state.readOnly).toBe(true);
            expect(view.chunks).toHaveLength(1);
            expect(diff().edited).toBe(false);

            const chunk = view.chunks[0];
            view.a.dispatch({
                changes: {
                    from: chunk.fromA,
                    to: chunk.toA,
                    insert: view.b.state.sliceDoc(chunk.fromB, chunk.toB),
                },
            });
            await nextTick();
            expect(diff().edited).toBe(true);

            diff().apply();
            expect(emitted).toEqual([
                'intro\n{% include "audience-summary-instructions.jinja2" %}\nSummarize.\n',
            ]);
        } finally {
            app.unmount();
            host.remove();
        }
    });

    it('reports an override identical to the default', async () => {
        const { app, host, diff } = mount({ overrideContent: 'same\n', defaultContent: 'same\n' });
        try {
            await nextTick();
            await nextTick();
            expect(diff().changeSummary).toBe('Identical to the default');
        } finally {
            app.unmount();
            host.remove();
        }
    });
});
