import { beforeEach, describe, expect, it, vi } from 'vitest';
import EntityHighlightMixin from '../../src/components/EntityHighlightMixin.js';
import {
    SELECTION_MAX_LENGTH,
    evaluateSelection,
    normalizeSelectionText,
    snapOffsetsToWords,
} from '../../src/utils/messageSelection.js';

const methods = EntityHighlightMixin.methods;

describe('selection text rules', () => {
    it('grows a partial word out to its boundaries', () => {
        const text = 'the beacon blinks';
        expect(snapOffsetsToWords(text, 6, 9)).toEqual([4, 10]);
    });

    it('leaves a selection that already sits on word boundaries alone', () => {
        const text = 'the beacon blinks';
        expect(snapOffsetsToWords(text, 4, 10)).toEqual([4, 10]);
    });

    it('does not grow across a space', () => {
        const text = 'the beacon blinks';
        expect(snapOffsetsToWords(text, 3, 4)).toEqual([3, 4]);
    });

    it('collapses whitespace and drops outer punctuation', () => {
        expect(normalizeSelectionText('  "the  dented\nlocker",  ')).toBe('the dented locker');
    });

    it('reports an empty selection', () => {
        expect(evaluateSelection('   ')).toEqual({ reason: 'empty', text: '' });
    });

    it('reports a selection past the cap', () => {
        const result = evaluateSelection('x'.repeat(SELECTION_MAX_LENGTH + 1));
        expect(result.reason).toBe('too-long');
    });

    it('accepts a selection at the cap', () => {
        const text = 'x'.repeat(SELECTION_MAX_LENGTH);
        expect(evaluateSelection(text)).toEqual({ reason: null, text });
    });
});

// --- fake DOM ---------------------------------------------------------------

globalThis.Node = { ELEMENT_NODE: 1, TEXT_NODE: 3 };

function messageWrapper(id, type = 'narrator') {
    return { id: `message-${id}`, dataset: { messageType: type } };
}

function textNode(text, { wrapper = null, insideEntity = false } = {}) {
    const parentElement = {
        closest: (selector) => {
            if (selector === '.scene-entity') return insideEntity ? { entity: true } : null;
            if (selector === '[id^="message-"]') return wrapper;
            return null;
        },
    };
    return { nodeType: 3, textContent: text, parentElement };
}

function fakeRange(node, start, end, endNode = node) {
    return {
        startContainer: node,
        endContainer: endNode,
        startOffset: start,
        endOffset: end,
        setStart(container, offset) {
            this.startContainer = container;
            this.startOffset = offset;
        },
        setEnd(container, offset) {
            this.endContainer = container;
            this.endOffset = offset;
        },
        toString() {
            if (this.startContainer !== this.endContainer) {
                return `${this.startContainer.textContent.slice(this.startOffset)} ${this.endContainer.textContent.slice(0, this.endOffset)}`;
            }
            return this.startContainer.textContent.slice(this.startOffset, this.endOffset);
        },
        getBoundingClientRect: () => ({ left: 10, width: 40, bottom: 80 }),
    };
}

function host({ range, playthrough = false, entityTarget = false } = {}) {
    globalThis.window = {
        getSelection: () => ({
            isCollapsed: !range,
            rangeCount: range ? 1 : 0,
            getRangeAt: () => range,
            removeAllRanges: vi.fn(),
        }),
    };
    return {
        ...methods,
        agentStatus: {
            world_state: {
                available: true,
                actions: {
                    update_world_state: {
                        enabled: true,
                        can_be_disabled: true,
                        config: { include_context_investigation: { value: true } },
                    },
                },
                scene_overrides: null,
            },
        },
        isPlaythroughActive: () => playthrough,
        entitySelection: { open: false, target: null, reason: null, text: '', messageId: null },
        event: {
            detail: 1,
            target: {
                closest: (selector) =>
                    selector === '.scene-entity' && entityTarget ? { entity: true } : null,
            },
        },
    };
}

describe('the floating add action', () => {
    let wrapper;

    beforeEach(() => {
        wrapper = messageWrapper(42);
    });

    it('offers the action for a selection inside one message', () => {
        const node = textNode('A dented locker sits here.', { wrapper });
        const context = host({ range: fakeRange(node, 4, 10) });

        methods.onMessageContainerMouseUp.call(context, context.event);

        expect(context.entitySelection.open).toBe(true);
        expect(context.entitySelection.messageId).toBe(42);
        // Snapped out to the whole words the partial selection touched.
        expect(context.entitySelection.text).toBe('dented locker');
        expect(context.entitySelection.target).toEqual([30, 80]);
    });

    it('says nothing when the selection spans two messages', () => {
        const first = textNode('A dented locker sits here.', { wrapper });
        const second = textNode('Elmer looks away.', { wrapper: messageWrapper(43) });
        const context = host({ range: fakeRange(first, 2, 5, second) });

        methods.onMessageContainerMouseUp.call(context, context.event);

        expect(context.entitySelection.open).toBe(false);
    });

    it('leaves a selection inside a highlight to the entity popover', () => {
        const node = textNode('A dented locker sits here.', { wrapper, insideEntity: true });
        const context = host({ range: fakeRange(node, 2, 8), entityTarget: true });

        methods.onMessageContainerMouseUp.call(context, context.event);

        expect(context.entitySelection.open).toBe(false);
    });

    it('leaves a double click to the inline editor', () => {
        const node = textNode('A dented locker sits here.', { wrapper });
        const context = host({ range: fakeRange(node, 2, 8) });
        context.event.detail = 2;

        methods.onMessageContainerMouseUp.call(context, context.event);

        expect(context.entitySelection.open).toBe(false);
    });

    it('says nothing on a message type the snapshot never looks at', () => {
        for (const type of ['director', 'time']) {
            const node = textNode('Three days pass.', { wrapper: messageWrapper(7, type) });
            const context = host({ range: fakeRange(node, 2, 8) });

            methods.onMessageContainerMouseUp.call(context, context.event);

            expect(context.entitySelection.open).toBe(false);
        }
    });

    it('offers the action on a context-investigation message while the setting is on', () => {
        const wrapperCI = messageWrapper(9, 'context_investigation');
        const node = textNode('A dented locker sits here.', { wrapper: wrapperCI });
        const context = host({ range: fakeRange(node, 4, 10) });

        methods.onMessageContainerMouseUp.call(context, context.event);

        expect(context.entitySelection.open).toBe(true);
        expect(context.entitySelection.messageId).toBe(9);
    });

    it('withholds it on a context-investigation message while the setting is off', () => {
        const wrapperCI = messageWrapper(9, 'context_investigation');
        const node = textNode('A dented locker sits here.', { wrapper: wrapperCI });
        const context = host({ range: fakeRange(node, 4, 10) });
        context.agentStatus.world_state.actions.update_world_state.config
            .include_context_investigation.value = false;

        methods.onMessageContainerMouseUp.call(context, context.event);

        expect(context.entitySelection.open).toBe(false);
    });

    it('says nothing while the World State agent cannot serve it', () => {
        const node = textNode('A dented locker sits here.', { wrapper });
        for (const agent of [
            undefined,
            { available: false },
            {
                available: true,
                // the real action declares can_be_disabled, so the stored flag
                // is what resolve_enabled reads
                actions: {
                    update_world_state: { enabled: false, can_be_disabled: true },
                },
            },
        ]) {
            const context = host({ range: fakeRange(node, 4, 10) });
            context.agentStatus = { world_state: agent };

            methods.onMessageContainerMouseUp.call(context, context.event);

            expect(context.entitySelection.open).toBe(false);
        }
    });

    // The backend resolves both flags through the scene overlay, so the gate
    // has to read the same effective value rather than the global one.
    it('follows a scene override that switches the setting on', () => {
        const wrapperCI = messageWrapper(9, 'context_investigation');
        const node = textNode('A dented locker sits here.', { wrapper: wrapperCI });
        const context = host({ range: fakeRange(node, 4, 10) });
        const agent = context.agentStatus.world_state;
        agent.actions.update_world_state.config.include_context_investigation.value = false;
        agent.scene_overrides = {
            actions: {
                update_world_state: {
                    config: { include_context_investigation: { value: true } },
                },
            },
        };

        methods.onMessageContainerMouseUp.call(context, context.event);

        expect(context.entitySelection.open).toBe(true);
        expect(context.entitySelection.messageId).toBe(9);
    });

    it('follows a scene override that switches the setting off', () => {
        const wrapperCI = messageWrapper(9, 'context_investigation');
        const node = textNode('A dented locker sits here.', { wrapper: wrapperCI });
        const context = host({ range: fakeRange(node, 4, 10) });
        context.agentStatus.world_state.scene_overrides = {
            actions: {
                update_world_state: {
                    config: { include_context_investigation: { value: false } },
                },
            },
        };

        methods.onMessageContainerMouseUp.call(context, context.event);

        expect(context.entitySelection.open).toBe(false);
    });

    it('follows a scene override that disables the snapshot action', () => {
        const node = textNode('A dented locker sits here.', { wrapper });
        const context = host({ range: fakeRange(node, 4, 10) });
        context.agentStatus.world_state.scene_overrides = {
            actions: { update_world_state: { enabled: false } },
        };

        methods.onMessageContainerMouseUp.call(context, context.event);

        expect(context.entitySelection.open).toBe(false);
    });

    it('stays out of playthrough mode', () => {
        const node = textNode('A dented locker sits here.', { wrapper });
        const context = host({ range: fakeRange(node, 2, 8), playthrough: true });

        methods.onMessageContainerMouseUp.call(context, context.event);

        expect(context.entitySelection.open).toBe(false);
    });

    it('shows the cap instead of the action for an over-long selection', () => {
        const long = 'x'.repeat(SELECTION_MAX_LENGTH + 10);
        const node = textNode(long, { wrapper });
        const context = host({ range: fakeRange(node, 0, long.length) });

        methods.onMessageContainerMouseUp.call(context, context.event);

        expect(context.entitySelection.open).toBe(true);
        expect(context.entitySelection.reason).toBe('too-long');
    });

    it('sends the selection and the message id, then closes', () => {
        const send = vi.fn();
        globalThis.window = { getSelection: () => ({ removeAllRanges: vi.fn() }) };
        const context = {
            ...methods,
            entitySelection: {
                open: true,
                target: [1, 2],
                reason: null,
                text: 'dented locker',
                messageId: 42,
            },
            getWebsocket: () => ({ send }),
        };

        methods.triggerAddSnapshotEntity.call(context);

        expect(context.entitySelection.open).toBe(false);
        expect(JSON.parse(send.mock.calls[0][0])).toEqual({
            type: 'world_state_agent',
            action: 'add_snapshot_entity',
            message_id: 42,
            text: 'dented locker',
        });
    });
});
