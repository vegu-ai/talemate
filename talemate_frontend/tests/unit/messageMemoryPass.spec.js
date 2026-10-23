// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import MessageMemoryPass from '@/components/MessageMemoryPass.vue';
import MessageToolbar from '@/components/MessageToolbar.vue';
import {
    isLongMemory,
    memoryMetaLabel,
    memoryPassChipTooltip,
    memoryPassSummary,
    replyQuote,
} from '@/utils/memoryPass';

const KEPT = {
    status: 'kept',
    candidates: 5,
    kept: [
        { text: 'Mara still owes Edwin two kroner.', retrieved: 'Edwin: She owes me two kroner.', kind: 'story', subject: null },
        { text: 'Edwin keeps the light.', retrieved: null, kind: 'character', subject: 'Edwin' },
    ],
    dropped: [
        { text: 'The tide turns at six.', retrieved: null, kind: 'insight', subject: null },
    ],
};

const mounted = [];
afterEach(() => {
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

function passthrough(tag, extraProps = []) {
    return defineComponent({
        props: extraProps,
        setup: (_, { slots, attrs }) => () => h(tag, attrs, [slots.prepend?.(), slots.default?.(), slots.activator?.({ props: {} })]),
    });
}

function mount(component, props) {
    const state = reactive(props);
    const app = createApp({ render: () => h(component, state) });
    app.component('VDialog', defineComponent({
        props: ['modelValue'],
        setup: (dialogProps, { slots }) => () => (dialogProps.modelValue ? h('div', { class: 'v-dialog' }, slots.default?.()) : null),
    }));
    for (const name of ['VCard', 'VCardTitle', 'VCardText', 'VSpacer', 'VDivider', 'VExpandTransition']) {
        app.component(name, passthrough('div'));
    }
    app.component('VIcon', passthrough('i'));
    app.component('VAlert', passthrough('div'));
    app.component('VTooltip', defineComponent({ props: ['text'],
        setup: (tipProps, { slots }) => () => h('span', { class: 'v-tooltip', 'data-text': tipProps.text }, slots.activator?.({ props: {} })) }));
    for (const name of ['VChip', 'VBtn']) {
        app.component(name, defineComponent({ props: ['prependIcon', 'icon'],
            setup: (_, { slots, attrs }) => () => h('button', { ...attrs, class: [attrs.class, name === 'VChip' ? 'v-chip' : 'v-btn'] }, slots.default?.()) }));
    }
    app.provide('createPin', () => {});
    app.provide('reviseMessage', () => {});
    app.provide('forkSceneInitiate', () => {});
    app.provide('generateTTS', () => {});
    app.provide('insertTimePassage', () => {});
    app.provide('visualizeMessage', () => {});
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    mounted.push([app, host]);
    return { host, state };
}

describe('memory pass helpers', () => {
    it('labels a memory by kind and subject', () => {
        expect(memoryMetaLabel({ kind: 'character', subject: 'Edwin' })).toBe('Character · Edwin');
        expect(memoryMetaLabel({ kind: 'story' })).toBe('Story');
        expect(memoryMetaLabel({ kind: 'unknown' })).toBe('Note');
    });

    it('summarises each outcome', () => {
        expect(memoryPassSummary(KEPT)).toBe('Chosen by Refine memories with AI from 5 memories retrieved, most useful first.');
        expect(memoryPassSummary({ status: 'none', candidates: 1, kept: [], dropped: [] }))
            .toBe('Refine memories with AI found nothing to keep among 1 memory retrieved.');
        expect(memoryPassSummary({ status: 'fallback', candidates: 1, kept: [{}], dropped: [] })).toBe('Used as retrieved.');
        expect(memoryPassChipTooltip(KEPT, 'Edwin')).toBe('The 2 memories Edwin drew on for this reply');
    });

    it('clamps only long memories', () => {
        expect(isLongMemory({ text: 'x'.repeat(320) })).toBe(false);
        expect(isLongMemory({ text: 'x'.repeat(321) })).toBe(true);
    });

    it('quotes a long reply at a word boundary', () => {
        expect(replyQuote('  Short   reply. ')).toBe('Short reply.');
        const quote = replyQuote('word '.repeat(60));
        expect(quote.endsWith('word…')).toBe(true);
        expect(quote.length).toBeLessThanOrEqual(161);
    });
});

describe('MessageMemoryPass', () => {
    it('lists the kept memories in order and reveals the original on request', async () => {
        const { host } = mount(MessageMemoryPass, { modelValue: true, result: KEPT, character: 'Edwin', text: 'Keep it.', color: 'orange' });
        const cards = [...host.querySelectorAll('.memory-card')];
        expect(cards.map(card => card.querySelector('.memory-text').textContent)).toEqual([
            'Mara still owes Edwin two kroner.',
            'Edwin keeps the light.',
        ]);
        expect(cards[1].textContent).toContain('Character · Edwin');
        expect(host.querySelector('.memory-retrieved')).toBeNull();
        cards[0].querySelector('.memory-toggle').click();
        await nextTick();
        expect(host.querySelector('.memory-retrieved').textContent).toBe('Edwin: She owes me two kroner.');
        expect(cards[1].querySelector('.memory-toggle')).toBeNull();

        expect(host.querySelector('.dropped-list')).toBeNull();
        [...host.querySelectorAll('.v-btn')].find(button => button.textContent.includes('Left out (1)')).click();
        await nextTick();
        expect(host.querySelector('.dropped-list').textContent).toContain('The tide turns at six.');
    });

    it('opens a long memory clamped with a Show more toggle', async () => {
        const long = { text: 'The Sorena ran timber. '.repeat(20), retrieved: null, kind: 'summary', subject: null };
        const result = { status: 'kept', candidates: 1, kept: [long], dropped: [] };
        const { host } = mount(MessageMemoryPass, { modelValue: true, result, character: 'Edwin', text: 'Keep it.' });
        expect(host.querySelector('.memory-text--clamped')).not.toBeNull();
        host.querySelector('.memory-more').click();
        await nextTick();
        expect(host.querySelector('.memory-text--clamped')).toBeNull();
        expect(host.querySelector('.memory-more').textContent).toBe('Show less');
    });

    it('has its own state for a pass that kept nothing', () => {
        const result = { status: 'none', candidates: 2, kept: [], dropped: KEPT.dropped };
        const { host } = mount(MessageMemoryPass, { modelValue: true, result, character: 'Edwin', text: 'Keep it.' });
        expect(host.querySelector('.memory-pass-empty').textContent).toContain('Nothing seemed worth recalling');
        expect(host.querySelector('.memory-card')).toBeNull();
    });

    it('lists memories the scene already showed under Left out, labelled', () => {
        const inScene = { text: 'Edwin hears Mara laugh.', retrieved: null, kind: 'story', subject: null, in_scene: true };
        const result = { status: 'kept', candidates: 2, kept: [], dropped: [inScene, KEPT.dropped[0]] };
        const { host } = mount(MessageMemoryPass, { modelValue: true, result, character: 'Edwin', text: 'Keep it.' });
        expect(host.querySelector('.memory-pass-empty').textContent).toContain('Nothing new to recall');
        expect(host.textContent).toContain('Everything Refine memories with AI chose from 2 memories retrieved was already in the scene.');
        expect(memoryPassChipTooltip(result, 'Edwin')).toBe("No retrieved memory reached Edwin's reply");
        // open from the start, since it is all there is to see
        const rows = [...host.querySelectorAll('.dropped-row')];
        expect(rows.map(row => row.querySelector('.dropped-note')?.textContent ?? null)).toEqual(['Already in the scene', null]);
    });

    it('explains a fallback to the retrieved memories', () => {
        const result = { status: 'fallback', candidates: 1, kept: [KEPT.dropped[0]], dropped: [] };
        const { host } = mount(MessageMemoryPass, { modelValue: true, result, character: 'Edwin', text: 'Keep it.' });
        expect(host.textContent).toContain('could not be read, so Edwin used the retrieved memories unchanged');
        expect(host.querySelectorAll('.memory-card')).toHaveLength(1);
    });
});

describe('MessageToolbar memories chip', () => {
    it('appears only with a result and opens the popup', async () => {
        const { host, state } = mount(MessageToolbar, { messageId: 3, memoryPass: null, memoryPassCharacter: 'Edwin' });
        expect(host.querySelector('[data-testid="memory-pass-chip"]')).toBeNull();
        let opened = 0;
        state.onOpenMemoryPass = () => { opened += 1; };
        state.memoryPass = KEPT;
        await nextTick();
        const chip = host.querySelector('[data-testid="memory-pass-chip"]');
        expect(chip.textContent).toContain('Memories');
        expect(chip.textContent).toContain('2');
        chip.click();
        expect(opened).toBe(1);
    });
});
