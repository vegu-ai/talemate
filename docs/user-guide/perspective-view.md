# View a character's perspective

In a Character perspectives story you can read each character's view next to the story itself. Above the scene tools, beside **Auto Save** and **Auto Progress**, click **View Perspective** and pick one of the active characters. The scene splits in two: the story stays on the left, and to the right of each message you see what that character noticed of it. Pick **None** to go back to the normal view. When the scene header is on, it shows a label such as **Edwin's Perspective** above the right column; the **x** on the label also closes the view. The choice is a temporary mode and is not saved; a reload starts with **None**.

A perspective uses the same colors as the story: spoken lines in double quotes stand out from the prose around them.

Perspectives keep the original passage's tense, narrator and style. A character's own message is kept verbatim, including any narrator aside inside it. The player character also receives full passages by default. To limit the player's view to what they can perceive, turn on **Analyze player perspective** in **Settings → Agents → Summarizer → Character Perspectives**; it is off by default and adds analysis independently of the effort setting. This affects stored views and the context used when the AI writes for the player, while the main story column stays unchanged. Existing valid views are kept when you change the setting.

For each audience that needs analysis, the Summarizer first lists the exact parts of the passage that the character cannot perceive, each with a short reason such as *inaudible* or *private-thought*. Then it deletes those parts and keeps the rest word for word. If a character can perceive everything, the passage is copied unchanged.

Where a removed part leaves a sentence broken, only that sentence is repaired, and the visible part of an action stays. Alice whispers *"The key is in the blue vase"* to Bob, and Cora stands too far away to hear. Cora's view says *I whispered something*: she saw the whisper, not the words. The same holds when the whispered words end in a question or exclamation mark (*"Is the key in the blue vase?" she whispered*), or when the whisper is told in its own sentence after the words. While Alice and Bob are playing together, Alice's private thought *I loved playing chess with Bob* becomes *I was playing chess with Bob* in Bob's view. The *I* still refers to Alice.

Talemate checks each view against its list. A view that keeps a listed part, or that changes, drops or adds a sentence away from a listed part, is rejected. With **Automatically repair analysis** on (the default), the Summarizer then asks again for that character only; otherwise the analysis stops with an error you can retry. The check cannot tell whether the list itself is right. A known limitation: the Summarizer sometimes lists a part the character can perceive, for example a thin door that lets a hidden listener hear, and that part is then missing from the view ([#783](https://github.com/vegu-ai/talemate-private/issues/783)).

![The scene split in two, with Edwin's perspective to the right of each message](/talemate/img/0.40.0/scene-perspective-split-view.png)

Say Mara writes in her notebook alone in her room. With **View Perspective: Edwin** the cell beside that message is empty, because Edwin was not there. An empty cell shows a small icon; hover it to read why it is empty: the character noticed nothing, the analysis did not run yet or failed, or the message is of a type that has no perspectives (a time passage or a director note, for example).

**Double-click a perspective to change it.** Press Enter to save, Shift+Enter for a new line, Escape to cancel. You can also double-click an empty cell to write a perspective yourself, as long as the message is one that characters can notice. Save an empty text to say that the character noticed nothing. Messages that have no perspectives cannot get one this way, and the introduction is read only here: every character who was present shares its text, and you change it in the **Scene Editor**.

Your text replaces only that one character's view of that one message, and it does not start an AI request. The Summarizer keeps your text when it analyzes the scene later. If you change the message itself, its perspectives are analyzed again and your text is replaced.

Later perspectives and summaries can be built on the one you changed. They stay as they are. When there are any, a note below the cell tells you how many, with an **Analyze them again** button. Click it only if your change should flow into them: they go back to the analysis, and your next turn makes one Summarizer request for each affected message.

## Related pages

- [Knowledge](/talemate/user-guide/world-editor/knowledge): the Character perspectives mode, its cost and how characters learn things.
- [Scene Header](/talemate/user-guide/scene-header#perspective-label): the perspective label in the header.
