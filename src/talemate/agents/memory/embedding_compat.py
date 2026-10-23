GTE_MODEL = "Alibaba-NLP/gte-base-en-v1.5"


def restore_gte_buffers(embedding_function, model_name: str):
    if model_name != GTE_MODEL:
        return

    model = embedding_function._model[0].auto_model
    if getattr(model, "_talemate_gte_buffers_initialized", False):
        return

    import torch

    # GTE initializes these non-persistent buffers only in its constructor;
    # Transformers 5's meta loading leaves them uninitialized.
    embeddings = model.embeddings
    with torch.device("cpu"), torch.random.fork_rng(devices=[]):
        reference = type(embeddings)(model.config)

    source_buffers = dict(reference.named_buffers())
    target_buffers = dict(embeddings.named_buffers())
    if source_buffers.keys() != target_buffers.keys():
        raise RuntimeError("GTE embedding buffers differ from its constructor")

    for name, source in source_buffers.items():
        parent_name, _, buffer_name = name.rpartition(".")
        parent = reference.get_submodule(parent_name) if parent_name else reference
        if buffer_name not in parent._non_persistent_buffers_set:
            continue
        target = target_buffers[name]
        target.copy_(source.to(device=target.device, dtype=target.dtype))

    model._talemate_gte_buffers_initialized = True
