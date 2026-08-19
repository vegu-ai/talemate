# Time Passage Management

Time passage messages mark the flow of time within your scene. They appear as clock-themed markers between scene messages and influence how the AI understands the temporal context of your story.

## Inserting Time Passages

### From the Scene Tools Menu

The primary way to advance time is through the :material-clock: **Advance Time** button in the [Scene Tools](scenario-tools.md#advance-time) tool bar. It opens a menu of grouped duration presets (Minutes, Hours, Days, Weeks, Months, Years) plus a **Custom...** option for arbitrary durations. By default, the [Narrator Agent](/talemate/user-guide/agents/narrator/) will narrate the time jump.

![Advance Time menu with grouped presets](../img/0.37.0/advance-time-menu.png)


### From the Scene View

You can insert time passage markers at any point in the scene history, not just at the end.

To insert a time passage after a specific message:

1. Hover over the message in the scene view after which you want time to pass
2. Click the **Time passage** button that appears underneath the message
3. Specify the duration (amount and unit)
4. Optionally give it a **chapter title**

Available time units: minutes, hours, days, weeks, months, years.

The chapter title is optional and names the stretch of scene the passage opens.
It is shown on the time passage marker and is what the chapter menu in
[Playthrough Mode](playthrough.md#moving-around) lists; without one, a chapter
is listed by its duration instead.

!!! note "Months and Years"
    Scene time is tracked as elapsed seconds, so months and years use fixed lengths: a month is 30 days and a year is 365 days. This applies both to advancing time and to how elapsed time is displayed.

![Inserting a time passage in the scene view](../img/0.36.0/time-passage-insert.png)

## Editing Time Passages

### In the Scene View

Time passage markers in the scene view can be edited by double-clicking them. This opens inline editing controls where you can change the duration amount and unit.

![Editing a time passage in the scene view](../img/0.36.0/time-passage-edit-scene.png)

1. **Double-click** the time passage message to enter edit mode
2. Adjust the **Amount** (numeric value) and **Unit** (minutes, hours, days, etc.)
3. Add or change the **Chapter title**, or clear it to remove the title
4. Click **Save** to apply the changes, or **Cancel** to discard them

### In the World State Manager

The World State Manager's history view also displays time passage entries with editable duration and chapter title fields. This provides an alternative interface for managing time passages, especially useful when reviewing the full history timeline — and it is the only one that reaches a passage inserted before a summarized entry, which sits too far back for the scene view to show.

![Time passage entry in the World State Manager history view](../img/0.36.0/time-passage-wsm-entry.png)

To edit a time passage in the World State Manager:

1. Open the **World State Manager** from the scene tools
2. Navigate to the **History** view
3. Locate the time passage entry
4. **Double-click** the entry to open inline editing
5. Adjust the amount, unit and chapter title, then click **Save**

## Deleting Time Passages

### From the Scene View

Each time passage marker in the scene view has a close button (visible on hover) that allows you to delete it. Click the close button to remove the time passage from the history.

### From the World State Manager

In the World State Manager history view, hover over a time passage entry to reveal a delete button. Click it and confirm the deletion.

!!! warning "Effect on Timestamps"
    Deleting or editing a time passage automatically recalculates all timestamps in the scene history that follow the changed entry. This ensures temporal consistency throughout the scene.

## How Time Passages Affect AI Context

Time passage messages serve several purposes in the AI context:

- They provide temporal context so the AI understands how much time has elapsed between events
- They influence the [Summarizer Agent](/talemate/user-guide/agents/summarizer/) -- events before a time jump are summarized separately
- They clear [actor directions](/talemate/user-guide/agents/director/settings/#direction-stickiness), ensuring directions given in one time period do not carry over

## Related Documentation

- [Scene Tools -- Advance Time](scenario-tools.md#advance-time) -- the main interface for advancing time
- [Narrator Agent Settings](/talemate/user-guide/agents/narrator/settings/#narrate-time-passage) -- configuring time passage narration
- [World Editor History](/talemate/user-guide/world-editor/history/) -- managing scene history
- [Scene Context History Review](prompts/context-history-review.md) -- reviewing how history is assembled into context
