# Embeddings

You can manage your available embeddings through the application settings.

Open the **:material-cog: Settings** tab in the top navigation and select **:material-cube-unfolded: Embeddings** under the **Presets** group.

!!! warning "INSTRUCTOR Embeddings Removed (0.35.0)"
    INSTRUCTOR embeddings are no longer supported. If you were using INSTRUCTOR embeddings, your configuration has been automatically reset to use the default embedding model (all-MiniLM-L6-v2).

    **Alternatives:**

    - **all-MiniLM-L6-v2** (default) - Fast local embedding, good for most use cases
    - **Alibaba-NLP/gte-base-en-v1.5** - More accurate local embedding
    - **OpenAI text-embedding-3-small** - Cloud-based option (requires API key)
    - **KoboldCpp Client API** - Use an embedding model loaded in KoboldCpp (see [KoboldCpp Embeddings](koboldcpp.md))

    Your existing scene memory databases will be re-imported automatically when you load them with the new embedding configuration.

<!--- --8<-- [start:embeddings_setup] -->
## Pre-configured Embeddings

### all-MiniLM-L6-v2

The default ChromaDB embedding. Also the default for the Memory agent unless changed.

Fast, but the least accurate.

### Alibaba-NLP/Gte-Base-En-V1.5

Sentence transformer model that is decently fast and accurate and will likely become the default for the Memory agent in the future.

### OpenAI text-embedding-3-small

OpenAI's current text embedding model. Fast and accurate, but not free.

## Adding an Embedding

You can add new embeddings by clicking the **:material-plus: Add new** button.

Select the embedding type and then enter the model name. When using sentence-transformer, make sure the modelname matches the name of the model repository on Huggingface, so for example `Alibaba-NLP/gte-base-en-v1.5`.

![Add new embedding](/talemate/img/0.39.0/embedding-settings-new-1.png)

!!! warning "New embeddings require a download"
    When you add a new embedding model and use it for the first time in the Memory agent, Talemate will download the model from Huggingface. This can take a while, depending on the size of the model and your internet connection.

    You can track the download in the talemate process window. A better UX based download progress bar is planned for a future release.

## Editing an Embedding

![Edit embedding](/talemate/img/0.39.0/embedding-settings-edit.png)

Select the existing embedding from the left side bar and you may change the following properties:

##### Trust Remote Code

For custom sentence-transformer models, you may need to toggle this on. This can be a security risk, so only do this if you trust the model's creator. It basically allows remote code execution.

!!! warning
    Only trust models from reputable sources.

##### Device

The device to use for the embeddings. This can be either `cpu` or `cuda`. Note that this can also be overridden in the Memory agent settings.

!!! note "Switching device without a restart (0.37.0)"
    Changing the device no longer requires restarting Talemate. The old model is released from ChromaDB's cache and any GPU memory it held is freed before the new device is applied, and the active scene's memory database is re-imported automatically.

##### Distance

The maximum distance for results to be considered a match. Different embeddings may require different distances, so if you find low accuracy, try changing this value.

##### Distance Mod

A multiplier applied to **Distance** when deciding whether a result is a match. The effective cutoff used during a search is `Distance × Distance Mod`, so this slider lets you fine-tune search sensitivity without changing the base distance.

- Range: `0.1` to `2.0`, in steps of `0.1`.
- Default: `1.0`.
- Lower values tighten the match (fewer, more relevant results).
- Higher values loosen the match (more results, lower relevance).

!!! info "Also tunable from the Context Database"
    The [Context Database](/talemate/user-guide/world-editor/context-db/#search-strictness) page exposes this same value as the **Search Strictness** slider, making it easy to adjust on the fly while testing searches. Changes made in either place are saved to the same preset.

##### Topic Threshold

The cosine similarity at which two facts share a [topic](/talemate/user-guide/agents/memory/settings/#topics), and the least similarity a retrieval query needs to the nearest topic for that topic to contribute. The useful value depends on the model, and 0.50 was measured for `all-MiniLM-L6-v2` only (facts about the same thing score around 0.5 to 0.65 against each other); the other shipped presets inherit that number as a starting point, not a measurement. The threshold compares a fact with the topic's first fact, so it is the same pairwise quantity. When every fact lands in its own topic or all of them in one, the memory agent logs a warning naming the direction to move. The Memory agent's Topics group can override it for every preset at once.

##### Distance Function

The function to use for calculating the distance. The default is `Cosine Similarity`, but you can also use `Inner Product` or `Squared L2`. The selected embedding may require a specific distance function, so if you find low accuracy, try changing this value.

##### Fast

This is just a tag to mark the embedding as fast. It doesn't actually do anything, but can be useful for sorting later on.

##### GPU Recommendation

This is a tag to mark the embedding as needing a GPU. It doesn't actually do anything, but can be useful for sorting later on.

##### Local

This is a tag to mark the embedding as local. It doesn't actually do anything, but can be useful for sorting later on.
<!--- --8<-- [end:embeddings_setup] -->