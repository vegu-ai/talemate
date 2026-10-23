# Prompt Templates

For clients that are in complete control of the prompt generation, such as the KoboldCpp or the Text-Generation-WebUI client, it is important to understand the concept of prompt templates.

## Clients that support prompt templates

- KoboldCpp
- llama.cpp
- Text-Generation-WebUI
- LMStudio
- TabbyAPI

## Am i using the correct prompt template?

For good results it is **vital** that the correct prompt template is specified for whichever model you have loaded.

Talemate does come with a set of pre-defined templates for some popular models, and has recently implemented automatic detection of the template via Huggingface's model metadata. However this does not always work, so understanding and specifying the correct prompt template is something you should familiarize yourself with.

If a client shows a yellow triangle next to it, it means that the prompt template is not set, and it is currently using the default `Alpaca` style prompt template.

![Client unknown prompt template](/talemate/img/0.26.0/client-unknown-prompt-template.png)

Click the two cogwheels to the right of the triangle to go to the client's editor on the Clients settings page.

The template name, preview and warning refresh when Talemate detects a model or template update, including while the client stays selected. Unsaved settings edits are preserved.

The preview shows a request the way the client sends it. With reasoning on, the coercion is not pre-filled: `{LLM coercion}` appears as an instruction at the end of the prompt. A [Reason Prefill](/talemate/user-guide/clients/reasoning/#reason-prefill), if set, still appears after the model's turn marker.

![Client editor with an unknown prompt template](/talemate/img/0.40.0/client-unknown-prompt-template-editor.png)

You can first try by clicking the `DETERMINE VIA HUGGINGFACE` button. This doesn't always work — it probes the model repository for a template in this order: a `chat_template.jinja2` or `chat_template.jinja` file, an example in the model's `README.md`, or the template set in the `tokenizer_config.json` file.

If that doesn't work, you can manually select the prompt template from the dropdown. 

In the case for `Phi-3-medium-128k-instruct-Q8_0` that is `Phi-3` - select it from the dropdown. The selection is applied and remembered for that model right away, so there is nothing to save for the template itself.

![Client assigned prompt template](/talemate/img/0.40.0/client-assigned-prompt-template.png)

The `MANAGE TEMPLATES` button next to it opens the [LLM Prompt Templates](/talemate/user-guide/prompts/llm-prompt-templates/) view, where templates can be added and edited.

**Lock Template** stops the template from being updated automatically when the model changes, pinning your selection to this client. Unlike the template selection itself this is a client setting, so it needs to be saved.

## Adding a new prompt template

The easiest way to add or edit prompt templates is from the **Prompts** view in the main toolbar. Open the **LLM Prompt Templates** tab to create new user templates, copy built-in templates as starting points, or paste a GGUF/llama.cpp chat template directly. See [LLM Prompt Templates](/talemate/user-guide/prompts/llm-prompt-templates/) for details.

User templates are stored in `./templates/llm-prompt/std/user/` and are gitignored, so they are preserved across Talemate updates. Built-in templates live in `./templates/llm-prompt/std/` and are read-only.

User templates appear in the client's **Prompt Template** dropdown with a `user/` prefix and are matched against model names the same way built-in templates are.
