/**
 * Playthrough mode: the reveal cursor and everything that paces it.
 *
 * A playthrough walks an existing scene from its beginning, one message at a
 * time. The cursor is a single integer - the number of messages revealed - so
 * every traversal is a re-slice; the pure helpers for that live in
 * `utils/playthrough.js`, and this is the stateful shell around them: the
 * replay/resume protocol, narration pacing and its debounce, the stale-audio
 * bookkeeping and progress persistence.
 *
 * What it needs from the host component:
 *
 *  - `websocket` — the app socket, for the `playthrough` and `tts` actions
 *  - `$refs.sceneMessages` — `messages` and `messageAt(i)`, the list the
 *    cursor indexes into
 *  - `$refs.audioQueue` — `stopAndClear()`, to drop audio the cursor moved on
 *    from
 *  - `agentStatus.tts` — whether there is a voice to narrate with
 *  - `busy` — the app's busy state, which PlaythroughTools also gets
 *  - `scene.data.playthrough_progress` — the position a previous playthrough
 *    of this scene was left on
 *  - `scrollInputIntoView()` — the app's own "put the input back in view" on
 *    the way out
 *
 * The host mounts `PlaythroughTools`, provides `isPlaythroughActive` /
 * `startPlaythrough` / `stopPlaythrough`, ORs `playthroughActive` into its
 * `uxLocked` / `isInputDisabled` reads, and calls `handlePlaythroughMessage`
 * from its websocket handler.
 */

import {
    anchorForReveal,
    AUTO_ADVANCE_DELAY_MS,
    clampReveal,
    FORKABLE_MESSAGE_TYPES,
    NARRATION_DEBOUNCE_MS,
    revealForAnchor,
    speakRequest,
} from '@/utils/playthrough.js';
import { newUuid } from '@/utils/uuid';

export default {
    data() {
        return {
            playthroughActive: false,
            playthroughRevealCount: 1,
            playthroughMessageCount: 0,
            playthroughChapters: [],
            playthroughAutoAdvance: false,
            // narration is independent of auto-advance: it speaks whatever the
            // cursor lands on, however the cursor got there
            playthroughNarration: true,
            playthroughSpeakTimer: null,
            playthroughSpeakSent: false,
            playthroughAwaitedMessageId: null,
            // narrations the cursor moved on from before they finished generating -
            // their chunks are still coming and must not play
            playthroughStaleMessageIds: [],
            // replays we asked for whose clear_screen has not arrived yet: while
            // this is positive, a clear_screen is one of ours opening rather than
            // the history being replaced under us
            playthroughReplaysUnopened: 0,
            // replays we asked for that have not finished arriving. Only the
            // completion that brings this to zero places the cursor - an earlier
            // replay's completion belongs to a history that is already superseded
            playthroughReplaysInFlight: 0,
            // where to put the cursor back when a replay was not the player's idea
            playthroughResumeAnchor: null,
            playthroughAdvanceTimer: null,
            // the cursor is held still while a dialog of the mode's own is open
            playthroughPaused: false,
            playthroughForkRequestId: null,
            playthroughForkMessageId: null,
            playthroughForkError: '',
        };
    },

    computed: {
        playthroughTtsReady() {
            return !!this.agentStatus.tts?.available;
        },

        // the gate PlaythroughTools puts on Space before it advances
        playthroughTakesSpace() {
            return this.playthroughActive && !this.busy
                && this.playthroughRevealCount < this.playthroughMessageCount;
        },
    },

    methods: {
        onSceneMessagesChanged({ count, chapters }) {
          this.playthroughMessageCount = count;
          this.playthroughChapters = chapters;
        },

        setPlaythroughActive(active) {
          if (active === this.playthroughActive) {
            return;
          }
          this.playthroughActive = active;
          if (!active) {
            this.cancelPlaythroughPacing();
            this.playthroughStaleMessageIds = [];
            this.playthroughReplaysUnopened = 0;
            this.playthroughReplaysInFlight = 0;
            this.playthroughResumeAnchor = null;
            this.playthroughAutoAdvance = false;
            this.playthroughPaused = false;
            this.playthroughForkRequestId = null;
            this.playthroughForkMessageId = null;
            this.playthroughForkError = '';
            this.playthroughRevealCount = 1;
            this.$nextTick(() => this.scrollInputIntoView());
          }
        },

        startPlaythrough() {
          this.requestPlaythroughReplay();
          this.setPlaythroughActive(true);
        },

        requestPlaythroughReplay() {
          this.playthroughReplaysUnopened += 1;
          this.playthroughReplaysInFlight += 1;
          this.websocket.send(JSON.stringify({ type: 'playthrough', action: 'start' }));
        },

        // The reveal cursor is an index into the message list, and only a replay
        // fills that list with the whole story. Handlers that stay reachable while
        // the mode runs - saving the scene outline in the world editor, editing a
        // time passage - re-emit the capped tail instead, which the cursor is not
        // an index into. Replay again and put the player back on the message they
        // were on.
        onPlaythroughHistoryReplaced() {
          if (this.playthroughReplaysUnopened > 0) {
            this.playthroughReplaysUnopened -= 1;
            return;
          }
          // the first capture is the one taken from a list the cursor was still an
          // index into; a later one would read the replaced history
          if (this.playthroughResumeAnchor == null) {
            this.playthroughResumeAnchor = anchorForReveal(
              this.$refs.sceneMessages?.messages || [], this.playthroughRevealCount);
          }
          this.requestPlaythroughReplay();
        },

        stopPlaythrough() {
          // a cursor that is not on anything still resolves to the first
          // message, so leaving a mode that is not running would record a
          // position the reader never reached
          if (!this.playthroughActive) {
            return;
          }
          this.rememberPlaythroughPosition();
          this.setPlaythroughActive(false);
        },

        // The message the cursor is on, when it is one a fork can be taken at:
        // the scene intro carries no id and is not part of the history, and the
        // types the scene view offers no Fork on are not forked from here
        // either - a context investigation is not even sent with a revision, so
        // the revision gate cannot see that its fork would be a shallow one.
        playthroughForkTarget() {
          const message = this.$refs.sceneMessages?.messageAt(this.playthroughRevealCount - 1);
          if (message?.id == null || !FORKABLE_MESSAGE_TYPES.includes(message.type)) {
            return null;
          }
          return message;
        },

        // Hold the cursor still while the fork dialog is up, so the reader does
        // not watch the story move on past what the fork will contain. Only the
        // cursor: the narration of the message they are on keeps playing, since
        // stopping it would cut the audio mid-sentence and - on cancel - ask the
        // voice agent to generate it a second time.
        pausePlaythroughPacing() {
          this.playthroughPaused = true;
          clearTimeout(this.playthroughAdvanceTimer);
          this.playthroughAdvanceTimer = null;
        },

        resumePlaythroughPacing() {
          if (!this.playthroughPaused) {
            return;
          }
          this.playthroughPaused = false;
          // a narration still running paces the next step itself when it ends;
          // this puts the timer back for the step that has nothing to wait for,
          // including a narration that finished while the dialog was open
          if (!this.playthroughSpeakSent && !this.playthroughSpeakTimer) {
            this.armPlaythroughAdvanceTimer();
          }
        },

        promptPlaythroughFork() {
          this.playthroughForkError = '';
          this.pausePlaythroughPacing();
        },

        cancelPlaythroughFork() {
          if (this.playthroughForkRequestId) {
            return;
          }
          this.playthroughForkMessageId = null;
          this.playthroughForkError = '';
          this.resumePlaythroughPacing();
        },

        // `messageId` is the message the toolbar asked for the name at, rather
        // than whatever the cursor holds now - see PlaythroughTools.promptFork.
        forkPlaythrough(saveName, messageId) {
          if (messageId == null || this.playthroughForkRequestId) {
            return;
          }
          this.playthroughForkError = '';
          this.playthroughForkMessageId = messageId;
          this.playthroughForkRequestId = newUuid();
          this.websocket.send(JSON.stringify({
            type: 'assistant',
            action: 'fork_new_scene',
            message_id: messageId,
            save_name: saveName,
            request_id: this.playthroughForkRequestId,
          }));
        },

        handlePlaythroughForkMessage(data) {
          if (data.type !== 'assistant' || data.action !== 'operation_done'
              || !this.playthroughForkRequestId
              || data.request_id !== this.playthroughForkRequestId) {
            return false;
          }
          this.playthroughForkRequestId = null;
          if (data.error) {
            this.playthroughForkError = data.error.message;
            return true;
          }
          const messageId = this.playthroughForkMessageId;
          this.playthroughForkMessageId = null;
          this.playthroughForkError = '';
          this.rememberPlaythroughPosition(messageId);
          this.setPlaythroughActive(false);
          return true;
        },

        savedPlaythroughAnchor() {
          return this.scene?.data?.playthrough_progress ?? null;
        },

        // The replay is all here, so this is where the position is restored: the
        // one the player left off on, or the one they were on when the history was
        // replaced under them.
        onPlaythroughReplayComplete() {
          if (!this.playthroughActive) {
            return;
          }
          this.playthroughReplaysInFlight = Math.max(0, this.playthroughReplaysInFlight - 1);
          if (this.playthroughReplaysInFlight > 0) {
            // a newer replay is still arriving; it carries the list the cursor
            // will be placed in
            return;
          }
          const messages = this.$refs.sceneMessages?.messages || [];
          const resumed = this.playthroughResumeAnchor;
          this.playthroughResumeAnchor = null;
          const reveal = revealForAnchor(messages, resumed ?? this.savedPlaythroughAnchor());
          this.playthroughRevealCount = reveal ?? 1;
          // whatever the cursor was on is still being narrated, so a replay the
          // player did not ask for must not start it over - unless the message it
          // was on is gone and the cursor had to move
          if (resumed == null || reveal === null) {
            this.onPlaythroughRevealed();
          }
        },

        // `at` records a position other than the cursor's - the fork records the
        // message it was taken at, which is where the reader left the story.
        rememberPlaythroughPosition(at = null) {
          // a read-only scene has nowhere to record progress, and asking anyway
          // would answer every exit with an error
          if (this.scene?.data?.immutable_save) {
            return;
          }
          const anchor = at ?? anchorForReveal(
            this.$refs.sceneMessages?.messages || [], this.playthroughRevealCount,
          );
          if (anchor === null || anchor === this.savedPlaythroughAnchor()) {
            return;
          }
          this.websocket.send(JSON.stringify({
            type: 'playthrough', action: 'save_progress', message_id: anchor,
          }));
        },

        advancePlaythrough() {
          this.setPlaythroughReveal(this.playthroughRevealCount + 1);
        },

        jumpPlaythrough(revealCount) {
          this.setPlaythroughReveal(revealCount);
        },

        restartPlaythrough() {
          this.setPlaythroughReveal(1);
        },

        setPlaythroughReveal(revealCount) {
          const next = clampReveal(revealCount, this.playthroughMessageCount);
          if (next === this.playthroughRevealCount) {
            return;
          }
          this.playthroughRevealCount = next;
          this.onPlaythroughRevealed();
        },

        togglePlaythroughAutoAdvance() {
          this.playthroughAutoAdvance = !this.playthroughAutoAdvance;
          this.onPlaythroughRevealed();
        },

        cancelPlaythroughPacing() {
          clearTimeout(this.playthroughAdvanceTimer);
          clearTimeout(this.playthroughSpeakTimer);
          this.playthroughAdvanceTimer = null;
          this.playthroughSpeakTimer = null;
          if (this.playthroughSpeakSent && this.playthroughAwaitedMessageId !== null) {
            // only a request that was actually sent can still have audio coming.
            // Bounded because the backend cancels generation with the same stop:
            // it is the last few requests that can still be in flight, not all of
            // them
            this.playthroughStaleMessageIds = [
              ...this.playthroughStaleMessageIds.filter(
                (id) => id !== this.playthroughAwaitedMessageId),
              this.playthroughAwaitedMessageId,
            ].slice(-8);
          }
          this.playthroughSpeakSent = false;
          this.playthroughAwaitedMessageId = null;
          // unconditional: a request whose generation has not produced audio yet
          // leaves nothing playing and nothing queued, and its chunks would
          // arrive and play over whatever the cursor moved on to
          this.$refs.audioQueue?.stopAndClear();
        },

        // Everything that paces a playthrough hangs off the cursor landing on a
        // message: narrate it if narration is on, and pace the next step on that
        // narration finishing - or on a plain delay when there is none.
        onPlaythroughRevealed() {
          this.cancelPlaythroughPacing();
          if (!this.playthroughActive) {
            return;
          }

          const message = this.$refs.sceneMessages?.messageAt(this.playthroughRevealCount - 1);
          const request = this.playthroughNarration
            ? speakRequest(message, this.playthroughTtsReady)
            : null;

          if (request) {
            this.playthroughAwaitedMessageId = request.message_id;
            // stepping back onto a message whose narration was abandoned asks for
            // it again, so it is no longer stale
            this.playthroughStaleMessageIds = this.playthroughStaleMessageIds.filter(
              (id) => id !== request.message_id);
            // stepping quickly must not queue up the narration of every message
            // stepped over
            this.playthroughSpeakTimer = setTimeout(() => {
              this.playthroughSpeakTimer = null;
              this.playthroughSpeakSent = true;
              this.websocket.send(JSON.stringify(request));
            }, NARRATION_DEBOUNCE_MS);
            return;
          }

          this.armPlaythroughAdvanceTimer();
        },

        armPlaythroughAdvanceTimer() {
          if (this.playthroughPaused
              || !this.playthroughActive
              || !this.playthroughAutoAdvance
              || this.playthroughRevealCount >= this.playthroughMessageCount) {
            return;
          }
          this.playthroughAdvanceTimer = setTimeout(() => {
            this.playthroughAdvanceTimer = null;
            this.advancePlaythrough();
          }, AUTO_ADVANCE_DELAY_MS);
        },

        onPlaythroughMessageSpoken(messageId) {
          if (!this.playthroughSpeakSent
              || messageId !== this.playthroughAwaitedMessageId) {
            return;
          }
          this.playthroughSpeakSent = false;
          this.playthroughAwaitedMessageId = null;
          // a narration that ends while the fork dialog is up must not step the
          // cursor; resuming picks the pacing back up
          if (this.playthroughActive && this.playthroughAutoAdvance
              && !this.playthroughPaused) {
            this.advancePlaythrough();
          }
        },

        togglePlaythroughNarration() {
          this.playthroughNarration = !this.playthroughNarration;
          this.onPlaythroughRevealed();
        },

        // Called before the app's other message handlers: the clear_screen
        // hook has to read the message list before SceneMessages empties it.
        // Returns true when the frame was ours and nothing else should see it.
        handlePlaythroughMessage(data) {
          if (this.handlePlaythroughForkMessage(data)) {
            return true;
          }
          if (data.type === 'clear_screen' && this.playthroughActive) {
            this.onPlaythroughHistoryReplaced();
            return false;
          }
          if (data.type === 'playthrough' && data.action === 'replay_complete') {
            this.onPlaythroughReplayComplete();
            return true;
          }
          return false;
        },
    },
};
