Revisions were introduced in version `0.30.0` and allow the editor to detect and fix repetition and unwanted prose.

Please see the [settings](/talemate/user-guide/agents/editor/settings/#revision) for more information on how to configure **:material-typewriter: Revisions**.

## Automatic revision

Once automatic revisions are enabled, if the editor finds an issue in a message you will see the following status updates:

![Editor revision status](/talemate/img/0.30.0/editor-revision-issue-identified.png)

![Editor revision status](/talemate/img/0.30.0/editor-revision-rewriting.png)

Once the revision is complete the editor agent will indicate that that it made some changes by showing the :material-message-text-outline: icon next to its name.

![Editor revision status](/talemate/img/0.30.0/editor-has-messages.png)

Click the :material-message-text-outline: icon to open the Agent Messages dialog to view the changes.

![Editor revision messages](/talemate/img/0.30.0/editor-revision-history.png)

Which message types are revised automatically is controlled by the [Automatic Revision Targets](/talemate/user-guide/agents/editor/settings/#automatic-revision-targets) setting. Character and narrator messages are included by default; context-investigation messages (the results of **Look at**, **Investigate**, and **Query**) can be added by enabling their target, which is off by default.

## Manual revision

You can also trigger a revision yourself on the most recent message without waiting for automatic revision (or with automatic revision turned off entirely).

When revision is enabled, hover over the latest character, narrator, or context-investigation message and click the **:material-typewriter: Revise** chip in its toolbar. The chip's label reflects the configured [revision method](/talemate/user-guide/agents/editor/settings/#revision-method) (for example, *Dedupe*, *Unslop*, or *Targeted Rewrite*).

A revision has one of three outcomes:

- The text was changed - it's added as a new version of the message; use the message's version paginator to step between the original and the revision.
- No changes were needed - the message is left untouched and a status notice confirms it.
- The revision failed or was cancelled - the message is left untouched.

Revisions never overwrite the original. See [Message revision history](/talemate/user-guide/interacting/#message-revision-history) for how to move between versions.
