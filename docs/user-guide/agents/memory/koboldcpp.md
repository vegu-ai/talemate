# KoboldCpp Embeddings

Talemate can leverage an embeddings model that is already loaded in your KoboldCpp instance.

## 1. Start KoboldCpp with an embeddings model

Launch KoboldCpp with the `--embeddingsmodel` flag so that it loads an embeddings-capable GGUF model alongside the main LLM:

```bash
koboldcpp_cu12.exe --model google_gemma-3-27b-it-Q6_K.gguf --embeddingsmodel bge-large-en-v1.5.Q8_0.gguf
```

## 2. Talemate will pick it up automatically

When Talemate starts, the **Memory** agent probes every connected client that advertises embedding support. If it detects that your KoboldCpp instance has an embeddings model loaded:

1. The Memory backend switches the current embedding to **Client API**.
2. The `client` field in the agent details shows the name of the KoboldCpp client.
3. A banner informs you that Talemate has switched to the new embedding. <!-- stub: screenshot -->

![Memory agent automatically switched to KoboldCpp embeddings](/talemate/img/0.31.0/koboldcpp-embeddings.png)

## 3. Reverting to a local embedding

Open the memory agent settings and pick a different embedding. See [Memory agent settings](/talemate/user-guide/agents/memory/settings).