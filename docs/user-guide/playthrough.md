# Playthrough Mode

Playthrough mode replays a scene from its beginning, one message at a time. It is
for re-reading a story you have already played — on your own, or with someone
watching — rather than for continuing it, so the mode offers no way to take the
story any further.

![A scene being replayed in playthrough mode](/talemate/img/0.40.0/playthrough-view.png)

## Starting a playthrough

Click the :material-play-box-outline: **Playthrough** chip in the
[quick settings](scenario-tools.md#quick-settings) above the scene tools.

![The Playthrough chip in the quick settings](/talemate/img/0.40.0/playthrough-chip.png)

The scene collapses to its first message and the scene tools and message input
are replaced by the playthrough toolbar. The chip is unavailable while an agent
is busy.

The whole history is loaded when the mode starts, rather than the last hundred
messages a scene normally opens with, so a long scene can be replayed from its
beginning.

## Advancing

Reveal the next message by clicking anywhere in the message area, pressing
:material-keyboard-space: **Space**, or using the **Advance** button. The view
follows along, so the message that just appeared is always in sight.

The reveal counter next to the scrubber shows where you are — `7 / 106`.

## Moving around

![The playthrough toolbar](/talemate/img/0.40.0/playthrough-toolbar.png)

- **Scrubber** — drag it to jump anywhere in the scene.
- **:material-format-list-bulleted: Chapters** — jump to the start of the scene
  or to any [time passage](time-passage.md) in it. Give a time passage a
  **chapter title** and it is listed under that name; otherwise it is listed by
  its duration.
- **Restart** — back to the first message.

Jumping backwards hides the messages after the new position again.

## Narration and auto-advance

- **:material-volume-high: Narration** — when on, each message the cursor lands
  on is spoken by the [Voice agent](agents/voice/index.md), however you got there,
  including stepping by hand. Stepping quickly does not queue up every message
  you pass — only the one you settle on is narrated.
- **:material-play-circle-outline: Auto-advance** — when on, the playthrough
  moves on by itself: after the current message has finished being narrated, or
  on a short delay when narration is off or no voice agent is available.

The two toggles are independent of each other. Narration is on by default and
keeps whatever you set it to for the rest of the session; auto-advance starts
off every time and is switched off again when the playthrough ends.

If narration is taking too long, the Advance button becomes a **Cancel** button
that aborts it.

## What the mode offers

A playthrough is a walkthrough of a story that is already written, so the
surfaces that would add to it are put away while it runs: the message input and
the scene tools are gone, per-message actions (edit, delete, regenerate,
revisions) are disabled, and the entity actions that ask the narrator for new
text are hidden.

Everything else keeps working normally — application and agent settings,
template browsing, the world editor and image generation.

## Leaving, and picking up where you left off

Leave with **Exit** or by pressing :material-keyboard-esc: **Escape**. The full
history comes back, along with the normal tools.

Your position is remembered in the scene, so starting a playthrough of the same
scene again resumes at the message you left off on. **Restart** followed by
**Exit** clears it, and the next playthrough starts at the beginning.

!!! note "Read-only scenes"
    Scenes shipped with Talemate are read-only, so progress cannot be recorded
    in them. Save a copy of the scene first if you want a playthrough of it to
    resume.
