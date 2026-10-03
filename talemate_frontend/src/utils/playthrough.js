/**
 * Pure helpers for playthrough mode's reveal cursor.
 *
 * The cursor is a single integer — the number of messages revealed so far —
 * so every traversal (advance, jump, chapter select, rewind) is a re-slice.
 */

/** How long an unspoken message stays on screen when auto-advance paces itself. */
export const AUTO_ADVANCE_DELAY_MS = 4000;

/** Stepping faster than this does not ask for narration of every message passed. */
export const NARRATION_DEBOUNCE_MS = 400;

/** The scene intro carries no id; the backend knows it under this sentinel. */
export const INTRO_ANCHOR = 'intro';

/** Message types the TTS agent can speak. */
export const SPOKEN_MESSAGE_TYPES = ['character', 'narrator', 'context_investigation'];

/**
 * Message types a fork can be taken at: the ones the scene view offers a Fork
 * chip on, which is where `MessageToolbar` is mounted without `show-fork`
 * turned off. The others carry no revision of their own to reconstruct from.
 */
export const FORKABLE_MESSAGE_TYPES = ['character', 'narrator'];

/**
 * A replay of a handful of messages has nothing to show, so the mode is not
 * offered below this many character and narrator messages. Other message types
 * are not part of the story a replay walks through.
 */
export const PLAYTHROUGH_MIN_MESSAGES = 15;

/** Whether a scene holds enough of a story to be worth replaying. */
export function playthroughAvailable(historyStats) {
    return (historyStats?.character_narrator_messages || 0) > PLAYTHROUGH_MIN_MESSAGES;
}

/**
 * Drawers the mode puts away, by the name `toggleNavigation` knows them under.
 * The director console acts on the scene, which a replay does not.
 */
const HIDDEN_DRAWERS = ['directorConsole'];

/**
 * Whether a replay refuses to open a drawer. The button is gone while the mode
 * runs, but a `talemate://` link the help agent wrote earlier still points at
 * one.
 */
export function playthroughBlocksNavigation(navigation, playthroughActive) {
    return !!playthroughActive && HIDDEN_DRAWERS.includes(navigation);
}

/** Messages the reveal cursor exposes; `null` means "not in playthrough". */
export function visibleMessages(messages, revealCount) {
    if (revealCount === null || revealCount === undefined) {
        return messages;
    }
    return messages.slice(0, clampReveal(revealCount, messages.length));
}

/**
 * The backdrop asset a passage had, from the scene's backdrop messages.
 * Outside playthrough, or in a story without backdrop messages, it is the
 * saved backdrop. Before the first revealed change it is what that change
 * replaced. Pending messages (an image still being generated) are skipped.
 */
export function playthroughBackdrop(messages, revealCount, savedBackdrop) {
    const changes = messages.filter((message) => message.type === 'scene_backdrop' && !message.pending);
    if (revealCount === null || revealCount === undefined || !changes.length) {
        return savedBackdrop;
    }
    const revealed = new Set(visibleMessages(messages, revealCount));
    const last = changes.filter((message) => revealed.has(message)).at(-1);
    return last ? last.backdrop : changes[0].previous_backdrop;
}

/**
 * TTS request for the message auto-advance just revealed, or null when it
 * cannot be spoken.
 */
export function speakRequest(message, ttsReady) {
    if (!ttsReady || !message || !SPOKEN_MESSAGE_TYPES.includes(message.type)) {
        return null;
    }
    if (!message.text) {
        return null;
    }
    // the scene intro is emitted without an id and is not part of history;
    // the backend knows it under a sentinel
    const isIntro = message.id === null || message.id === undefined;
    return {
        type: 'tts',
        action: 'generate_for_scene_message',
        message_id: isIntro ? INTRO_ANCHOR : message.id,
    };
}


/**
 * Where a saved anchor sits in the replayed history, or null when there is
 * nothing to resume to — no anchor, or a message that is no longer there.
 *
 * The anchor is the id of the message the cursor was on rather than its
 * index, so an edited history resumes at the same message. Null has to be
 * distinguishable from position 1: the replay streams in message by message,
 * and "not there yet" must not read as "start at the beginning".
 */
export function revealForAnchor(messages, anchor) {
    if (anchor === null || anchor === undefined) {
        return null;
    }
    if (anchor === INTRO_ANCHOR) {
        return 1;
    }
    const index = messages.findIndex((message) => message.id === anchor);
    return index < 0 ? null : index + 1;
}

/**
 * The anchor to persist for a cursor: the id of the message it is on.
 *
 * The scene intro has no id and is the start of the scene, which the sentinel
 * says explicitly — "no position" has to stay distinguishable from "the
 * beginning", or a Restart followed by an Exit would leave the old position
 * behind.
 */
export function anchorForReveal(messages, revealCount) {
    const index = clampReveal(revealCount, messages.length) - 1;
    if (index < 0) {
        return null;
    }
    return messages[index].id ?? INTRO_ANCHOR;
}

/** A reveal cursor always names at least one message and never overshoots. */
export function clampReveal(revealCount, total) {
    if (total <= 0) {
        return 0;
    }
    return Math.min(Math.max(revealCount, 1), total);
}

/**
 * Where the reveal cursor goes when the chapter a time passage opens is picked:
 * the message after the divider — unless that is another divider, which leaves
 * the chapter empty and its own divider the only thing in it to land on.
 */
function chapterReveal(messages, index) {
    const opening = messages[index + 1];
    return opening && opening.type !== 'time' ? index + 2 : index + 1;
}

/**
 * Chapter boundaries: the scene start plus every time passage. `index` is the
 * message index the chapter is marked by; `reveal` is the cursor a jump to it
 * sets.
 */
export function chapterBoundaries(messages) {
    const chapters = [{ index: 0, reveal: 1, title: null, text: null }];
    messages.forEach((message, index) => {
        if (message.type === 'time') {
            chapters.push({
                index,
                reveal: chapterReveal(messages, index),
                title: message.title || null,
                text: message.text || null,
            });
        }
    });
    return chapters;
}

/** Label for a chapter menu entry: its title, or the time text it opens on. */
export function chapterLabel(chapter, position) {
    if (chapter.title) {
        return chapter.title;
    }
    if (chapter.text) {
        return `${position}. ${chapter.text}`;
    }
    return `${position}. Scene start`;
}

/** Index of the chapter the reveal cursor currently sits in. */
export function currentChapter(chapters, revealCount) {
    let current = 0;
    chapters.forEach((chapter, i) => {
        if (chapter.index < revealCount) {
            current = i;
        }
    });
    return current;
}

/**
 * Whether an audio chunk belongs to a narration the playthrough moved on from.
 *
 * The audio queue is application-wide, so this has to be scoped to the
 * abandoned requests rather than to "anything other than the one we are waiting
 * for": a chunk with no message id belongs to nobody in particular - a voice
 * test from the agent settings, say - and has to keep playing.
 */
export function chunkIsAbandoned(messageId, staleMessageIds) {
    if (messageId === null || messageId === undefined) {
        return false;
    }
    return (staleMessageIds || []).includes(messageId);
}
