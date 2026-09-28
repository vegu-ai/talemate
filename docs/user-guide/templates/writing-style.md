# Writing Styles and Decision Checks

Writing style templates are used to define a writing style that can be applied to the generated content. They can be used to add a specific flavor or tone. A template must explicitly support writing styles to be able to use a writing style template.

## Creating a writing style

--8<-- "docs/snippets/common.md:world-editor-create-group"

Next enter a template name and select **Writing style** as a template type.

### Template name

The name / label of the template. This is the name that will be displayed in the list of templates.

### Template type

Specify the type of template you are creating. In this case, select **Writing style**.

Once the template type is selected, the form will update to show the fields required for a writing style template.

![world editor templates create writing style template 1](/talemate/img/0.26.0/world-editor-templates-create-writing-style-template-1.png)

### Template description

A longer description of the template. What is the purpose of the template? What should it be used for?

### Writing style instructions

This should be the actual writing style instructions. It will be passed to the AI to generate content in the specified style.

##### Example

> Write in a clear, engaging style typical of modern sci-fi, with accessible language and vivid descriptions of futuristic concepts.

or

> Use a narrative writing style that reminds of mid 90s point and click adventure games.

### Favorite

Mark the template as a favorite to make it easier to find in the list of templates.

Favorited templates will be shown at the top of the list of templates.

### Phrase Detection

![Writing Style Phrase Detection](/talemate/img/0.30.0/writing-style-phrase-detection.png)

Introduced in version `0.30.0` the writing style can now define certain phrases that should be detected in the content and handled in a specific way through the [Editor Agent's Revision Actions](/talemate/user-guide/agents/editor/settings#revision).

!!! note "Writing style needs to be set in the scene"
    In order for the writing style's phrase detection to work, the writing style needs to be set in the [Scene Settings](/talemate/user-guide/world-editor/scene/settings).

Specifically this allows you to define a list of phrases that you do NOT want in your content. 

There are two methods of phrase matching

1. Regex (Regular Expressions) - This will match any phrase that matches the regex pattern.
2. Semantic Similarity - This will match any phrase that has a semantic similarity above the defined threshold. Semantic similarity is calculated using the Memory agent's embedding function.

#### Regex

While you can certainly do overly complex regex patterns, most of time you will simply want to do groups of words that should be removed.

For example

```
We're in this together as (a team|partners|friends)
```

This will match these three combinations:

- We're in this together as a team
- We're in this together as partners
- We're in this together as friends

If you are about to write a more complex pattern, consider switching to semantic similarity.

#### Semantic Similarity

Semantic similarity is a more flexible way to match phrases. It will match any phrase that has a semantic similarity above the defined threshold.

!!! warning
    This has the potential to do A LOT of requests to the embedding model as each sentence in the content is compared to each phrase. Batching is used when available, but its not advisable to use this with remote embedding APIs at this point (openai etc.).

When running with local embeddings, using CUDA is highly recommended.


### Deactivation

You can deactivate defined phrases by unselecting the **Active** checkbox, at which point it will no longer be considered for phrase detection.

### Decision checks

![Writing style decision checks](/talemate/img/0.40.0/writing-style-decision-checks.png)

Decision checks are questions the Editor asks the optional
[Decision Model](../app-settings/decision-model.md) about new text, to find passages that need
a rewrite. A writing style holds the checks and their
settings, so different styles can ask different questions. New styles start with
no checks.

Click **Add default checks** to add the common checks in one action, including
while creating a new writing style. It adds:

- **Repeated beats and description reuse**, with separate questions for redundant
  story events and reused distinctive descriptions. The latter keeps the event
  and changes its description.
- **Writing style and unwanted prose**, which checks the style instructions and
  active phrase rules.

Each check starts at a probability threshold of **0.80**, shown as **Flags at 0.80** in the list. The button adds missing
default questions without replacing your edits or adding duplicate questions.
If a check with the same name already exists, the added check gets a numbered
name, such as **Repeated beats and description reuse (2)**.

Click **Edit** to change a check's name, threshold and questions. Each question has a
**Question**, a **Rewrite instruction** and a **Finding type**. Use `{passage_id}` in a
question or its criteria to refer to the passage being evaluated. The model also receives
the full current text, preceding history, style instructions and active prose rules.
The token is optional: without it, the Editor names the passage before your question.

**More options** under each question holds the optional settings:

- **What counts as yes** and **What counts as no** are optional guidance (the true and
  false criteria). Fill both to use them; if either is blank, the check uses its
  question without either criterion.
- **Short name** (the question ID) identifies the answer in the Decision Log. It must be
  unique within the style.

Click **Apply check** to keep the edit, or **Cancel** to discard it.

A check can contain several questions sharing one threshold. Use **Add custom
check** to give another question its own threshold. For example, a terse mystery
style could ask whether a passage explains a character's feelings instead of
showing an action, and instruct the rewrite to replace that explanation with a
physical detail. Its threshold can differ from the repetition check's threshold.

**Finding type** categorizes the finding as repetition or writing style/unwanted prose.
The rewrite instruction tells the selected Revision method how to correct it.
The **Only run when this writing style has instructions or active prose rules** option
omits that check when neither kind of guidance is available. Uncheck a check to make
it inactive, or click **Remove** to delete it.

When loading a shared or hand-edited template file, invalid check settings are
repaired where possible and logged as warnings. An unusable check is omitted;
the writing style's instructions and phrase rules remain available. Review the
checks after importing a file that reports warnings.

To use the checks, select this writing style in **World Editor → Scene → Settings**,
enable the Decision Model, then turn on **Decision checks** in **Editor → Revision**
with **Targeted Rewrite** or **Unslop** selected. Successful checks replace the
usual detection and can lead to at most one revision call. If no passage meets
its check's threshold, the text stays unchanged. With no style selected, no
checks, or no active applicable checks, Revision uses its usual detection without
a decision request. See [Editor settings](../agents/editor/settings.md#decision-checks)
for failure handling and the Decision Log.

## Create the template

When you have filled out the form, click the **:material-cube-scan: Create Template** button to create the template.

## Using the writing style template

Please see the [Generation settings](/talemate/user-guide/world-editor/generation-settings) section for general information on how to apply a writing style template during generation.

### Example: Update character's description

Go to the [Character Editor - Description](/talemate/user-guide/world-editor/characters/description) section of the World Editor.

In the **:material-auto-fix: Generation Settings** on top of the world editor, click the **:material-script-text: Writing Style** dropdown and select the writing style template you just created.

![world editor templates create writing style template 2](/talemate/img/0.26.0/world-editor-templates-create-writing-style-template-2.png)

![world editor templates create writing style template 3](/talemate/img/0.26.0/world-editor-templates-create-writing-style-template-3.png)

This will apply the writing style toi any content generations you do.

Next, click the **:material-auto-fix: Generate** button bove the character description to generate a new description for the character using the selected writing style. (Hold `alt` if you want to do a rewrite of the existing content)


## Editing a writing style template

To edit an existing template, select it from the list of templates in the left sidebar.

Then adjust any of the fields in the form that appears.

Updates are appied automatically and there is no need to manually save the template.

## Deleting a writing style template

To delete a template, select it from the list of templates in the left sidebar, then click the **:material-close-box-outline: Remove Template** button.
