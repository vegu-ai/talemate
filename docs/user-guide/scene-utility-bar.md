# Scene Utility Bar

!!! info "New in 0.40.0"

![Scene utility bar](/talemate/img/0.40.0/scene-utility-bar.png)

A compact bar at the top of the scene area that stays in view while the scene scrolls. It shows the scene title in the middle and a set of information items on either side of it.

```text
[ Left of the title: items ]   [ Scene title ]   [ Right of the title: items ]
```

Both slots hold as many items as you like, in the order you pick them, and either slot can be empty. A long title is cut short with an ellipsis; hover over it to read the whole title. Hover over any item for an explanation of what its number means.

The bar is hidden while [Playthrough Mode](playthrough.md) runs.

Because the bar carries the title, the scene's tab in the main navigation reads **:material-script: Story** rather than the scene title, in both the gameplay and the creative environment.

## Items

##### :material-layers-outline: History stats

Two chips: the number of messages in the scene history (including messages that have already been summarized) and the number of summary layers. The base archive counts as the first summary layer once it holds a summary; each populated layer of the [layered history](/talemate/user-guide/agents/summarizer/settings/#layered-history) adds one. The World Editor's History tab shows the same layers as **Base**, **Layer 0**, **Layer 1** and so on.

Until the scene reports its history, the chip reads **History stats unavailable**.

##### :material-archive-arrow-down-outline: Summarizer

The dialogue tokens gathered since the last summary against the [summarizer](/talemate/user-guide/agents/summarizer/)'s threshold, for example **798 / 1536 tokens**. The tooltip says how many more tokens take the scene past the threshold, after which the summarizer archives the recent messages. A time passage or a change in who is present can trigger a summary earlier, so that remainder is a ceiling, not a countdown.

When a summary is due on the next message, the chip changes colour and gains a :material-archive-clock-outline: marker; the count stays visible. The tooltip names the reason: the gathered dialogue passed the threshold, a time passage cut the span, or who is present changed.

When the summarizer has no ready client the chip reads **Summarizer unavailable**.

## Turning the bar off and on

Hover over the bar and click the **:material-close:** button at its right edge to hide it. The button is also reachable with the keyboard and always visible on touch screens. Hiding the bar this way turns off the same setting as **Show scene utility bar** in [Settings > Game > General](/talemate/user-guide/app-settings/game#scene-utility-bar), which is where you turn it back on. Your slot choices are kept while the bar is hidden.

## Choosing the items

Open [Settings > Game > General](/talemate/user-guide/app-settings/game#scene-utility-bar) and pick items for **Left of the title** and **Right of the title**. The bar updates when you save.

By default the bar is on, with **History stats** on the left and **Summarizer** on the right.
