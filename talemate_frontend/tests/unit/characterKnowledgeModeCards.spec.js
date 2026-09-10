// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h } from 'vue';
import Cards from '@/components/CharacterKnowledgeModeCards.vue';
import { CHARACTER_KNOWLEDGE_MODES } from '@/constants/characterKnowledgeModes';

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });

let app, host;

beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(Cards, { perspectives: false });
    for (const name of ['VRow', 'VCol', 'VCard', 'VCardTitle', 'VCardText', 'VChip', 'VIcon']) {
        app.component(name, Container);
    }
    app.mount(host);
});

afterEach(() => {
    app?.unmount();
    host?.remove();
});

const cards = () => [...host.querySelectorAll('.mode-card')];
const follows = (first, second) => Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);

describe('the mode cards put the decision first', () => {
    it('draws one card per mode, each with a pick-this-if callout', () => {
        expect(cards()).toHaveLength(CHARACTER_KNOWLEDGE_MODES.length);
        for (const [index, card] of cards().entries()) {
            const pick = card.querySelector('.mode-pick');
            expect(pick, `${CHARACTER_KNOWLEDGE_MODES[index].title} has no callout`).not.toBeNull();
            expect(pick.textContent).toContain(CHARACTER_KNOWLEDGE_MODES[index].pickIf);
        }
    });

    it('renders the callout, so it cannot be hidden and still pass', () => {
        for (const card of cards()) {
            const pick = card.querySelector('.mode-pick');
            expect(pick.hidden).toBe(false);
            const style = getComputedStyle(pick);
            expect(style.display).not.toBe('none');
            expect(style.visibility).not.toBe('hidden');
            expect(pick.textContent.trim().length).toBeGreaterThan(0);
        }
    });

    it('places the callout after the title and before the summary, the pros and the cons', () => {
        for (const [index, card] of cards().entries()) {
            const mode = CHARACTER_KNOWLEDGE_MODES[index];
            const pick = card.querySelector('.mode-pick');
            // the element that carries the text and is not an ancestor of the callout
            const text = (needle) => [...card.querySelectorAll('*')].find((el) => !el.contains(pick) && el.textContent.includes(needle));
            const title = text(mode.title);
            const summary = text(mode.summary);
            const pros = text(mode.pros[0]);
            const cons = text(mode.cons[0]);
            for (const [name, element] of Object.entries({ title, summary, pros, cons })) {
                expect(element, `${mode.title} has no ${name}`).toBeTruthy();
            }
            expect(follows(title, pick), `${mode.title}: the callout does not follow the title`).toBe(true);
            for (const [name, element] of Object.entries({ summary, pros, cons })) {
                expect(follows(pick, element), `${mode.title}: the ${name} does not follow the callout`).toBe(true);
            }
        }
    });
});
