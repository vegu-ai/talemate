// @vitest-environment jsdom

import { describe, expect, it } from 'vitest';
import EntityHighlightMixin, { INTRO_ANCHOR_ID } from '../../src/components/EntityHighlightMixin.js';
import { SceneTextParser } from '../../src/utils/sceneMessageRenderer.js';

const mentions = [{ name: 'Dented Locker', kind: 'item', phrases: ['the dented locker'] }];

function render(text, options = { mentions }) {
    return new SceneTextParser().parse(text, options);
}

function spans(html) {
    const host = document.createElement('div');
    host.innerHTML = html;
    return [...host.querySelectorAll('.scene-entity')];
}

describe('where an entity mention becomes a highlight', () => {
    it('marks it in plain prose', () => {
        expect(spans(render('She opened the dented locker.'))).toHaveLength(1);
    });

    // Scene prose puts action inside asterisks, and emphasis renders its own
    // source instead of parsing it — so a mention there reached no tokenizer.
    it('marks it inside emphasis', () => {
        const [span] = spans(render('*She opened the dented locker.*'));
        expect(span.textContent).toBe('the dented locker');
        expect(span.dataset.entityName).toBe('Dented Locker');
        expect(span.dataset.entityKind).toBe('item');
    });

    it('marks it inside strong', () => {
        expect(spans(render('**She opened the dented locker.**'))).toHaveLength(1);
    });

    it('marks it inside quoted speech', () => {
        expect(spans(render('"Look at the dented locker."'))).toHaveLength(1);
    });

    it('marks only the first occurrence across emphasis and plain prose', () => {
        const html = render('*She opened the dented locker.* Then the dented locker groaned.');
        const marked = spans(html);
        expect(marked).toHaveLength(1);
        // the first occurrence is the emphasised one, so that is where the
        // span has to sit — a count alone cannot tell this apart from the
        // renderer that could only mark the plain-prose occurrence
        expect(marked[0].closest('.scene-emphasis')).not.toBeNull();
    });

    it('leaves the text alone when highlighting is switched off', () => {
        const parser = new SceneTextParser({ entities: { show: false } });
        const html = parser.parse('*She opened the dented locker.*', { mentions });
        expect(spans(html)).toHaveLength(0);
        expect(html).toContain('the dented locker');
    });

    it('marks nothing when the snapshot supplied no mentions', () => {
        expect(spans(render('*She opened the dented locker.*', { mentions: [] }))).toHaveLength(0);
    });
});

// The payload the World State agent emits is the only source of highlights:
// EntityHighlightMixin turns it into the mention list every message component
// feeds to the parser.
describe('from the world_state payload to the parser', () => {
    const payload = {
        characters: {},
        items: {
            'Dented Locker': {
                snapshot: 'Its door is welded shut.',
                mentions: ['the dented locker'],
                manual: true,
            },
        },
        places: {},
        anchor_message_ids: [42],
    };

    function host(anchorIds = payload.anchor_message_ids) {
        const context = { ...EntityHighlightMixin.methods, ...EntityHighlightMixin.data() };
        context.rebuildWorldStateEntities({ ...payload, anchor_message_ids: anchorIds });
        return context;
    }

    it('feeds a manually added entity to an anchored message', () => {
        expect(host().getEntityMentionsForMessage(42)).toEqual([
            { name: 'Dented Locker', kind: 'item', phrases: ['the dented locker'] },
        ]);
    });

    it('feeds nothing to a message outside the moment', () => {
        expect(host().getEntityMentionsForMessage(41)).toEqual([]);
    });

    // The intro arrives as a narrator frame with a null id.
    it('feeds the intro when the snapshot anchored it', () => {
        const context = host([INTRO_ANCHOR_ID, 42]);
        expect(context.getEntityMentionsForMessage(null)).toHaveLength(1);
        expect(context.getEntityMentionsForMessage(undefined)).toHaveLength(1);
    });

    it('feeds nothing to the intro outside the moment', () => {
        expect(host().getEntityMentionsForMessage(null)).toEqual([]);
    });

    it('renders the highlight the payload describes', () => {
        const context = host();
        const html = render(
            '*She opened the dented locker.*',
            { mentions: context.getEntityMentionsForMessage(42) },
        );
        expect(spans(html)).toHaveLength(1);
    });

    it('keeps the entity looked up by the popover', () => {
        expect(host().worldStateEntityIndex['item:Dented Locker']).toMatchObject({
            name: 'Dented Locker',
            kind: 'item',
            snapshot: 'Its door is welded shut.',
        });
    });
});
