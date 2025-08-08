# Kokoro

Kokoro provides predefined voice models and voice mixing capabilities for creating custom voices.

## Using Predefined Voices

Kokoro comes with built-in voice models that are ready to use immediately

Available predefined voices include various male and female voices with different characteristics.

## Creating Mixed Voices

Kokor allows you to mix voices together to create a new voice.

### Voice Mixing Interface


To create a mixed voice:

1. Open the Voice Library
2. Click ":material-plus: New"
3. Select "Kokoro" as the provider
4. Choose ":material-tune:Mixer" option
5. Configure the mixed voice:

![Voice mixing interface](/talemate/img/0.32.0/kokoro-mixer.png)


**Label:** Descriptive name for the mixed voice

**Base Voices:** Select 2-4 existing Kokoro voices to combine

**Weights:** Set the influence of each voice (0.1 to 1.0)

**Tags:** Descriptive tags for organization

### Weight Configuration

Each selected voice can have its weight adjusted:

- Higher weights make that voice more prominent in the mix
- Lower weights make that voice more subtle
- Total weights need to sum to 1.0
- Experiment with different combinations to achieve desired results

### Saving Mixed Voices

Once configured click "Add Voice", mixed voices are saved to your voice library and can be:

- Assigned to characters
- Used as narrator voices  

just like any other voice.

Saving a mixed cvoice may take a moment to complete.