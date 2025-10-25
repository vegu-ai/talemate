# Template Locking

Template locking allows you to prevent a client's prompt template from automatically updating when the model changes. This is useful when you want to maintain a consistent prompt format across different models or when you've customized a template for a specific use case.

## What is Template Locking?

By default, Talemate automatically determines the appropriate prompt template for each model you load. When you switch models, the prompt template updates to match the new model's requirements. Template locking disables this automatic behavior, keeping your selected template fixed regardless of model changes.

## When to Use Template Locking

Some models have reasoning and non-reasoning variants of their templates. This allows you to lock one client to the reasoning template and another to the non-reasoning template.

## How to Lock a Template

### Step 1: Open Client Settings

Start with your client that has a template already assigned (either automatically detected or manually selected):

![Lock Template - Starting Point](/talemate/img/0.33.0/client-lock-template-0001.png)

1. Open the client settings by clicking the cogwheels icon next to the client
2. Review the currently assigned template in the preview area

### Step 2: Enable Template Lock

When you check the **Lock Template** checkbox, the current template selection is cleared and you must select which template to lock:

![Lock Template - Select Template](/talemate/img/0.33.0/client-lock-template-0002.png)

1. Check the **Lock Template** checkbox
2. You'll see the message: "Please select a prompt template to lock for this client"
3. Select your desired template from the dropdown menu

This gives you the opportunity to choose which specific template you want to lock, rather than automatically locking whatever template happened to be active.

### Step 3: Template Locked

Once you've selected a template and clicked **Save**:

![Lock Template - Locked](/talemate/img/0.33.0/client-lock-template-0003.png)

- The template display shows your locked template with its name (e.g., `TextGenWebUI__LOCK.jinja2`)
- The template will no longer automatically update when you change models
- The lock icon indicates the template is fixed

## Understanding the Lock Template Setting

When the **Lock Template** checkbox is enabled:

- The prompt template will not automatically update when you change models

When disabled:

- Talemate automatically determines the best template for your loaded model
- Templates update when you switch models
- The system attempts to match templates via HuggingFace metadata

## Unlocking a Template

To return to automatic template detection:

1. Open the client settings
2. Uncheck the **Lock Template** checkbox
3. Click **Save**
4. Re-open the client settings and confirm that the template is no longer locked and the correct template is selected.

## Related Topics

- [Prompt Templates](/talemate/user-guide/clients/prompt-templates/) - Learn more about how prompt templates work
- [Client Configuration](/talemate/user-guide/clients/) - General client setup and configuration
