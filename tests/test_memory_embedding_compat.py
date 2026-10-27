from types import SimpleNamespace

import torch

from talemate.agents.memory.embedding_compat import GTE_MODEL, restore_gte_buffers


class Rotary(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("inv_freq", torch.arange(2).float(), persistent=False)
        self.register_buffer("cos_cached", torch.ones(8, 2), persistent=False)
        self.register_buffer("sin_cached", torch.zeros(8, 2), persistent=False)


class Embeddings(torch.nn.Module):
    def __init__(self, config):
        super().__init__()
        self.word_embeddings = torch.nn.Embedding(8, 2)
        self.register_buffer("position_ids", torch.arange(8), persistent=False)
        self.register_buffer("checkpoint_buffer", torch.zeros(2))
        self.rotary_emb = Rotary()


def test_gte_restores_all_derived_buffers_without_changing_checkpoint_or_rng():
    embeddings = Embeddings(None)
    expected = {name: value.clone() for name, value in embeddings.named_buffers()}
    weights = embeddings.word_embeddings.weight.detach().clone()
    for buffer in embeddings.buffers():
        buffer.fill_(42)
    model = SimpleNamespace(embeddings=embeddings, config=None)
    function = SimpleNamespace(_model=[SimpleNamespace(auto_model=model)])
    rng = torch.random.get_rng_state().clone()

    restore_gte_buffers(function, GTE_MODEL)

    for name, buffer in embeddings.named_buffers():
        if name == "checkpoint_buffer":
            assert torch.equal(buffer, torch.full_like(buffer, 42))
        else:
            assert torch.equal(buffer, expected[name]), name
    assert torch.equal(embeddings.word_embeddings.weight, weights)
    assert torch.equal(torch.random.get_rng_state(), rng)

    embeddings.position_ids.fill_(7)
    restore_gte_buffers(function, GTE_MODEL)
    assert torch.equal(
        embeddings.position_ids, torch.full_like(embeddings.position_ids, 7)
    )


def test_other_embedding_models_are_not_inspected():
    restore_gte_buffers(object(), "all-MiniLM-L6-v2")
