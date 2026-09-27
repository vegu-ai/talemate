# Playthrough Mode

Playthrough mode replays a scene from its beginning, one message at a time. It is
for re-reading a story you have already played — on your own, or with someone
watching. Nothing is added to the story while it runs, so the way onward is to
[fork](#forking-from-where-you-are) it into a scene of your own.

![A scene being replayed in playthrough mode](/talemate/img/0.40.0/playthrough-view.png)

## Starting a playthrough

Click the :material-play-box-outline: **Playthrough** chip in the
[quick settings](scenario-tools.md#quick-settings) above the scene tools.

![The Playthrough chip in the quick settings](/talemate/img/0.40.0/playthrough-chip.png)

The scene collapses to its first message and the scene tools and message input
are replaced by the playthrough toolbar. The chip is unavailable while an agent
is busy.

The chip is only there when the scene holds more than 15 character and narrator
messages. A shorter story has too little to walk through. Other message types —
time passages, director messages and the rest — are not counted.

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
  or to any [time passage](time-passage.md) in it, landing on the first message
  after the passage — or on the passage itself when another follows it straight
  away and the chapter is empty. Give a time passage a **chapter title** and it
  is listed under that name; otherwise it is listed by its duration.
- **Restart** — back to the first message.
- **:material-source-fork: Fork from here** — leave the replay and carry the
  story on in a scene of your own, described [below](#forking-from-where-you-are).

Jumping backwards hides the messages after the new position again.

## Narration and auto-advance

- **:material-volume-high: Narration** — when on, each message the cursor lands
  on is spoken by the [Voice agent](agents/voice/index.md), however you got there,
  including stepping by hand. Stepping quickly does not queue up every message
  you pass — only the one you settle on is narrated. The toggle is only there
  when the Voice agent is enabled.
- **:material-play-circle-outline: Auto-advance** — when on, the playthrough
  moves on by itself: after the current message has finished being narrated, or
  on a short delay when narration is off or no voice agent is available.

The two toggles are independent of each other. Narration is on by default and
keeps whatever you set it to for the rest of the session; auto-advance starts
off every time and is switched off again when the playthrough ends.

If narration is taking too long, the Advance button becomes a **Cancel** button
that aborts it.

## Forking from where you are

**:material-source-fork: Fork from here** takes the message you are on and makes
a new scene of the story up to that point. Name the save and the new scene opens
in the normal scene view, ready to be played on from there.

The scene you were replaying is left as it was, apart from remembering where you
had got to, and the fork is a save of its own — an existing save is never
written over. If a name is already in use, the dialog stays open so you can pick
a different one.

What the fork contains is restored from the scene's
[revision history](restoring-scenes.md): the story, the world state and the
characters as they were at the message you forked from. The history is recorded
in steps rather than per message, so a fork can carry a message or two that were
recorded in the same step as the one you picked. A message the scene
recorded no revision for — anything played before Talemate kept a history — is
forked by copying the scene and cutting its story at that message instead, which
may leave world state and character details that belong to a later point in the
story.

The story forks at the messages the scene view offers a **Fork** on — what a
character said and what the narrator wrote. On anything else the cursor can land
on, the scene intro and time passages among them, the action is unavailable, as
it is on a message whose revision the scene has not saved yet: with
[Auto Save](scenario-tools.md#quick-settings) off, leave the playthrough and save
the scene to fork from those. Forking a scene that draws on a shared world
context disconnects it from that context.

## What else the mode offers

A playthrough is a walkthrough of a story that is already written, so the
surfaces that would add to it are put away while it runs:

- The message input and the scene tools are replaced by the playthrough toolbar.
- The [scene header](scene-header.md) keeps the scene title and puts its
  information items and its header buttons away. With the header turned off,
  a playthrough shows no title bar.
- Per-message actions — edit, delete, regenerate, revisions — are disabled, and
  the entity actions that ask the narrator for new text are hidden.
- The **:material-bullhorn: Director console** and its chat are gone, along with
  the activity chip that announces what the director is doing.
- The **:material-chart-timeline-variant-shimmer: node editor** and the **Mods**
  tab are gone.
- The world panel in the sidebar no longer offers to update the world state, or
  to make one of its characters real.

Everything else keeps working normally — application and agent settings,
template browsing, the world editor and image generation. All of it comes back
when the playthrough ends.

The [Help assistant](agents/help/index.md) knows when a playthrough is running,
so it explains that the mode has put a surface away rather than walking you
through opening it.

## Leaving, and picking up where you left off

Leave with **Exit** or by pressing :material-keyboard-esc: **Escape**. The full
history comes back, along with the normal tools.

Your position is remembered in the scene — on the way out, when you load another
scene, and when you fork — so starting a playthrough of the same scene again
resumes at the message you left off on. **Restart** followed by
**Exit** clears it, and the next playthrough starts at the beginning.

!!! note "Read-only scenes"
    Scenes shipped with Talemate are read-only, so progress cannot be recorded
    in them. Save a copy of the scene first if you want a playthrough of it to
    resume.
