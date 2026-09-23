import EntityTooltip from './EntityTooltip.vue';
import EntitySelectionAction from './EntitySelectionAction.vue';
import {
    dispatchAddSnapshotEntity,
    dispatchExamineEntity,
    dispatchLookAtEntity,
    isKnownSceneCharacter,
} from '@/utils/entityActions';
import { evaluateSelection, snapOffsetsToWords } from '@/utils/messageSelection';
import {
    effectiveActionEnabled,
    effectiveConfigValue,
} from '@/constants/sceneAgentSettings';

// The message types the world-state snapshot can anchor a highlight to.
// director and time messages are permanent members of the agent's ignore list,
// so a selection there could never become one. A context-investigation message
// joins them only while "Include Look at / Add Detail" is on.
const SELECTABLE_MESSAGE_TYPES = new Set(['character', 'narrator']);
const CONTEXT_INVESTIGATION = 'context_investigation';

// The anchor id the World State agent gives the scene intro, which is not a
// scene message. Mirrors INTRO_ANCHOR_ID in src/talemate/world_state/__init__.py.
export const INTRO_ANCHOR_ID = 0;

// Shared empty array for messages with no entity highlights — using the same
// reference avoids invalidating the entityMentions prop on every parent render.
const NO_ENTITY_MENTIONS = Object.freeze([]);

/**
 * Inline entity-highlight + tooltip behaviour for the chat view.
 *
 * Drives the "examine in the latest message" affordance: receives the
 * world_state event payload, exposes a per-message mention list to feed to
 * the SceneTextParser, owns the popover lifecycle for the click-tooltip,
 * and dispatches the examine→context-investigation flow when the user
 * clicks "Examine" on a highlighted entity.
 *
 * Requirements on the host component:
 *  - Template: bind `:entityMentions="getEntityMentionsForMessage(message.id)"`
 *    on every message component that should render highlights, and add
 *    `@click="onMessageContainerClick"` on the message container element.
 *  - Template: mount `<EntitySelectionAction
 *        :model-value="entitySelection.open"
 *        :target="entitySelection.target"
 *        :reason="entitySelection.reason"
 *        @update:model-value="onEntitySelectionUpdate"
 *        @add="triggerAddSnapshotEntity" />` and add
 *    `@mouseup="onMessageContainerMouseUp"` on the message container element.
 *  - Template: mount `<EntityTooltip
 *        :model-value="entityTooltip.open"
 *        :activator="entityTooltip.activator"
 *        :entity="entityTooltip.entity"
 *        @update:model-value="onEntityTooltipUpdate"
 *        @configure-highlights="onConfigureEntityHighlights"
 *        @examine="triggerExamineEntity"
 *        @look-at="triggerLookAtEntity" />`.
 *  - In the host's `handleMessage(data)`, call
 *    `this.rebuildWorldStateEntities(data.data)` when
 *    `data.type === 'world_state' && data.status !== 'requested' && data.data`.
 *  - The host must pass an `agentStatus` prop — the action is offered only
 *    while the World State agent can serve it.
 *  - Template: stamp `:data-message-type="message.type"` on the same element
 *    that carries the `message-<id>` id.
 *  - The host must inject `getWebsocket` — the mixin dispatches the
 *    `world_state_agent.examine_entity` and `narrator.*` actions over the
 *    socket.
 *  - CSS for `.scene-entity` spans lives in the host (scoped + `:deep()`),
 *    since style blocks can't ride along on a mixin.
 */
export default {
    components: { EntityTooltip, EntitySelectionAction },

    inject: {
        isPlaythroughActive: { default: () => () => false },
    },

    data() {
        return {
            // World-state entity highlighting state — populated by the
            // 'world_state' websocket event. Highlights are only rendered on
            // messages whose id appears in worldStateAnchorIds (every focus
            // message the agent included in the snapshot pass).
            worldStateAnchorIds: new Set(),
            // Flat list passed to SceneTextParser: [{ name, kind, phrases }]
            worldStateMentions: [],
            // Lookup for tooltip content: { "kind:name": { name, kind, snapshot, emotion } }
            worldStateEntityIndex: {},
            // Entity tooltip popover state
            entityTooltip: {
                open: false,
                activator: null,
                entity: null,
            },
            // Floating "Add to world state" action for a text selection.
            // `target` is a viewport coordinate pair rather than an element —
            // a selection spans text nodes and has no element to anchor to.
            entitySelection: {
                open: false,
                target: null,
                reason: null,
                text: '',
                messageId: null,
            },
        };
    },

    mounted() {
        document.addEventListener('click', this.onDocumentClickForTooltip);
        document.addEventListener('mousedown', this.onDocumentMouseDownForSelection);
    },

    beforeUnmount() {
        document.removeEventListener('click', this.onDocumentClickForTooltip);
        document.removeEventListener('mousedown', this.onDocumentMouseDownForSelection);
    },

    methods: {
        // Return the entity-mention list to feed to the SceneTextParser for
        // this message — only messages that were part of the latest
        // world-state snapshot's focus span get highlights; everything else
        // gets the shared empty sentinel so the prop reference stays stable
        // across re-renders. The intro is the one slot rendered without an id.
        getEntityMentionsForMessage(messageId) {
            if (!this.worldStateAnchorIds.has(messageId ?? INTRO_ANCHOR_ID)) return NO_ENTITY_MENTIONS;
            return this.worldStateMentions;
        },

        // Rebuild the parser-facing mentions list and the tooltip lookup
        // from a fresh world_state event payload.
        rebuildWorldStateEntities(payload) {
            const mentions = [];
            const index = {};
            const ingest = (kind, dict) => {
                if (!dict) return;
                for (const name in dict) {
                    const entry = dict[name] || {};
                    const phrases = Array.isArray(entry.mentions) ? entry.mentions : [];
                    if (phrases.length > 0) {
                        mentions.push({ name, kind, phrases });
                    }
                    index[`${kind}:${name}`] = {
                        name,
                        kind,
                        snapshot: entry.snapshot || null,
                        emotion: entry.emotion || null,
                    };
                }
            };
            ingest('character', payload.characters);
            ingest('item', payload.items);
            ingest('place', payload.places);

            this.worldStateMentions = mentions;
            this.worldStateEntityIndex = index;
            this.worldStateAnchorIds = new Set(payload.anchor_message_ids || []);
        },

        // Delegated click handler on the message container. When the click
        // lands on a `.scene-entity` span emitted by the SceneTextParser,
        // look up the entity and open the tooltip menu anchored to the span.
        onMessageContainerClick(event) {
            const span = event.target.closest?.('.scene-entity');
            if (!span) return;
            const name = span.getAttribute('data-entity-name');
            const kind = span.getAttribute('data-entity-kind');
            if (!name || !kind) return;
            const entity = this.worldStateEntityIndex[`${kind}:${name}`];
            if (!entity) return;
            event.stopPropagation();
            this.openEntityTooltip(span, entity);
        },

        // True when `name` is a live Scene actor (active or inactive roster).
        characterIsKnown(name) {
            return isKnownSceneCharacter(this.scene?.data, name);
        },

        openEntityTooltip(activator, entity) {
            // Stamp whether a character entity is a live Scene actor. Existing
            // characters have their own detail surfaces (sheet, attributes,
            // progression), so Add Detail is hidden for them — but background
            // characters (named in narrative, not actors) have no other
            // fleshing-out path, so they keep it like items and places do.
            const enriched =
                entity?.kind === 'character'
                    ? { ...entity, isKnownCharacter: this.characterIsKnown(entity.name) }
                    : entity;
            this.entityTooltip = { open: true, activator, entity: enriched };
        },

        // Flip the menu closed but keep `activator` and `entity` populated —
        // setting them to null synchronously crashes v-menu's leave
        // transition, which still reads coordinates from the activator while
        // animating out.
        closeEntityTooltip() {
            if (!this.entityTooltip.open) return;
            this.entityTooltip = { ...this.entityTooltip, open: false };
        },

        // We own close behaviour ourselves (the menu is `persistent`).
        // Document-level clicks land here when a click was NOT on an entity
        // span — our delegated handler calls stopPropagation in that case.
        // Clicks inside the menu content are also ignored.
        onDocumentClickForTooltip(event) {
            if (!this.entityTooltip.open) return;
            if (event.target.closest?.('.v-overlay__content')) return;
            if (event.target.closest?.('.scene-entity')) return;
            this.closeEntityTooltip();
        },

        onEntityTooltipUpdate(open) {
            // v-menu emits update:modelValue both for explicit closes and
            // for spurious transitions while the activator changes. We only
            // honour explicit opens — close is owned by closeEntityTooltip.
            if (open && !this.entityTooltip.open) {
                this.entityTooltip = { ...this.entityTooltip, open: true };
            }
        },

        onConfigureEntityHighlights() {
            this.closeEntityTooltip();
            this.$emit('configure-entity-highlights');
        },

        triggerExamineEntity(entity) {
            if (!entity || !entity.snapshot) return;
            this.closeEntityTooltip();
            dispatchExamineEntity(this.getWebsocket(), {
                name: entity.name,
                kind: entity.kind,
                snapshot: entity.snapshot,
            });
        },

        // Delegated mouseup on the message container. A drag or shift-click
        // that leaves a selection inside one message offers to add it to the
        // world state. A selection inside an existing highlight is left to the
        // click handler above, which opens the entity popover instead, and a
        // double click is left to the inline editor.
        onMessageContainerMouseUp(event) {
            if (this.isPlaythroughActive()) return;
            if (!this.worldStateCanAddEntity()) return;
            // A double click has already selected a word by mouseup, and the
            // dblclick that follows opens the inline editor — offering the
            // card here would leave it floating over a textarea.
            if (event.detail >= 2) return;
            if (event.target.closest?.('.scene-entity')) return;

            const selection = window.getSelection?.();
            if (!selection || selection.isCollapsed || selection.rangeCount === 0) return;

            const range = selection.getRangeAt(0);
            const messageId = this.resolveSelectionMessageId(range);
            if (messageId === null) return;

            this.snapRangeToWords(range);
            const evaluated = evaluateSelection(range.toString());
            if (evaluated.reason === 'empty') return;

            const rect = range.getBoundingClientRect();
            this.entitySelection = {
                open: true,
                target: [rect.left + rect.width / 2, rect.bottom],
                reason: evaluated.reason,
                text: evaluated.text,
                messageId,
            };
        },

        // True while the World State agent is on, has a client and has its
        // snapshot action enabled — a card the agent cannot serve would spend a
        // click on a failure toast. Effective values: the backend resolves both
        // the action and its config through the scene overlay, so a scene
        // override has to reach this gate too.
        worldStateCanAddEntity() {
            const agent = this.agentStatus?.world_state;
            if (!agent?.available) return false;
            return effectiveActionEnabled(
                agent.actions,
                agent.scene_overrides,
                'update_world_state',
            );
        },

        // Whether a Look at / Add Detail message counts as part of the current
        // moment — with the setting off the agent skips the type, so an entry
        // added from one could carry no highlight.
        worldStateIncludesContextInvestigation() {
            const agent = this.agentStatus?.world_state;
            return effectiveConfigValue(
                agent?.actions,
                agent?.scene_overrides,
                'update_world_state.config.include_context_investigation',
            ) === true;
        },

        // The message id both ends of the selection sit in, or null when the
        // selection spans two messages, lands outside one, or lands on a
        // message type the snapshot never looks at.
        resolveSelectionMessageId(range) {
            const element = (node) =>
                (node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement) || null;
            const wrapperOf = (node) => element(node)?.closest?.('[id^="message-"]') || null;
            const start = wrapperOf(range.startContainer);
            if (!start || start !== wrapperOf(range.endContainer)) return null;
            const type = start.dataset?.messageType;
            const selectable =
                SELECTABLE_MESSAGE_TYPES.has(type)
                || (type === CONTEXT_INVESTIGATION
                    && this.worldStateIncludesContextInvestigation());
            if (!selectable) return null;
            const messageId = parseInt(start.id.slice('message-'.length), 10);
            return Number.isFinite(messageId) ? messageId : null;
        },

        // Grow the live range outward so neither edge cuts a word in half. The
        // user sees their selection snap, and the phrase we send can match on
        // the word boundaries the highlight parser needs.
        snapRangeToWords(range) {
            const { startContainer, endContainer } = range;
            if (startContainer.nodeType === Node.TEXT_NODE) {
                const [from] = snapOffsetsToWords(
                    startContainer.textContent,
                    range.startOffset,
                    range.startOffset,
                );
                range.setStart(startContainer, from);
            }
            if (endContainer.nodeType === Node.TEXT_NODE) {
                const [, to] = snapOffsetsToWords(
                    endContainer.textContent,
                    range.endOffset,
                    range.endOffset,
                );
                range.setEnd(endContainer, to);
            }
        },

        closeEntitySelectionAction() {
            if (!this.entitySelection.open) return;
            this.entitySelection = { ...this.entitySelection, open: false };
        },

        // A press anywhere outside the card dismisses it — including the press
        // that starts the next selection, which lands before the mouseup that
        // would reopen it.
        onDocumentMouseDownForSelection(event) {
            if (event.target.closest?.('.v-overlay__content')) return;
            this.closeEntitySelectionAction();
        },

        onEntitySelectionUpdate(open) {
            if (!open) {
                this.closeEntitySelectionAction();
            }
        },

        triggerAddSnapshotEntity() {
            const { text, messageId } = this.entitySelection;
            this.closeEntitySelectionAction();
            window.getSelection?.()?.removeAllRanges();
            dispatchAddSnapshotEntity(this.getWebsocket(), { messageId, text });
        },

        triggerLookAtEntity(entity) {
            if (!entity || !entity.name) return;
            this.closeEntityTooltip();
            dispatchLookAtEntity(this.getWebsocket(), {
                name: entity.name,
                kind: entity.kind,
                isKnownCharacter: this.characterIsKnown(entity.name),
            });
        },
    },
};
