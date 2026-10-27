"""Memory documents are checked against the revisions of the history as it is
at the check: a stale revision is rejected, also one that went stale while
the retrieval awaited, and one read of the history serves all checks with no
await between them."""

import asyncio
from types import SimpleNamespace

import pytest

from test_revision_browsing import standard_revision
from talemate.agents.memory.schema import MemoryDocument
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge import revision_browsing
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.knowledge.revision_browsing import RevisionCheck, RevisionCurrency
from talemate.scene_message import NarratorMessage, SceneMessage


def history_doc(archive_id: str) -> MemoryDocument:
    return MemoryDocument("x", meta={"typ": "history"}, id=archive_id, raw="x")


def message_doc(message_id) -> SimpleNamespace:
    return SimpleNamespace(
        id="k", meta={"knowledge_kind": "message", "knowledge_id": message_id}
    )


def count_reads(monkeypatch) -> list:
    reads = []
    from_scene = RevisionCurrency.from_scene.__func__

    def counting(cls, scene):
        reads.append(1)
        return from_scene(cls, scene)

    monkeypatch.setattr(
        revision_browsing.RevisionCurrency, "from_scene", classmethod(counting)
    )
    return reads


def test_stale_revision_rejects_its_archive_and_message_documents(scene):
    _, _, message = standard_revision(scene)
    revisions = RevisionCurrency.from_scene(scene)

    assert revisions.stale
    assert not revisions.document_current(history_doc("A1"))
    assert not revisions.document_current(message_doc(message.id))
    assert revisions.document_current(history_doc("A2"))


def test_committed_revision_is_current_again(scene):
    _, _, message = standard_revision(scene)
    message.mark_revision_committed()
    revisions = RevisionCurrency.from_scene(scene)

    assert not revisions.stale
    assert revisions.document_current(history_doc("A1"))
    assert revisions.document_current(message_doc(message.id))


def test_unknown_or_unreadable_message_documents_are_not_current(scene):
    standard_revision(scene)
    revisions = RevisionCurrency.from_scene(scene)

    assert not revisions.document_current(message_doc(99999))
    assert not revisions.document_current(message_doc("not an id"))
    assert revisions.source_current(None)


def test_an_edit_gives_a_new_digest_and_a_stale_source(scene):
    _, _, message = standard_revision(scene)
    message.mark_revision_committed()
    digest = message.revision_digest()
    assert RevisionCurrency.from_scene(scene).source_current(message.id)

    message.append_version("Alice: The key is gold.", "revision")

    assert message.revision_digest() != digest
    assert not RevisionCurrency.from_scene(scene).source_current(message.id)


def test_in_place_meta_change_gives_a_new_digest():
    message = NarratorMessage(message="The tide turns.", meta={"a": 1})
    digest = message.revision_digest()

    message.meta["a"] = True

    assert message.revision_digest() != digest


def test_later_message_with_the_same_id_decides_its_source_only(scene):
    _, _, message = standard_revision(scene)
    scene.history.append(NarratorMessage(message="Another line.", id=message.id))
    revisions = RevisionCurrency.from_scene(scene)

    assert revisions.source_current(message.id)
    # the earlier, stale message still makes its archive stale
    assert revisions.stale
    assert not revisions.document_current(history_doc("A1"))
    current = get_agent("conversation").rag_knowledge_filter(None)
    assert current is not None
    assert not current(history_doc("A1"))


def test_rag_filter_rejects_a_stale_archive_document(scene):
    standard_revision(scene)
    conversation = get_agent("conversation")
    character = scene.character_data["Alice"]

    current = conversation.rag_knowledge_filter(character)

    assert current is not None
    assert not current(history_doc("A1"))


@pytest.mark.asyncio
@pytest.mark.parametrize("viewer", [True, False])
async def test_filter_rejects_a_revision_that_went_stale_during_the_retrieval(
    scene, viewer
):
    _, _, message = standard_revision(scene)
    message.mark_revision_committed()
    # a stale line outside every archive, so that the filter exists without
    # a viewer too
    stale_elsewhere = NarratorMessage(message="A stale line.")
    stale_elsewhere.revision_state = stale_elsewhere.revision_state.model_copy(
        update={"baseline_digest": "old"}
    )
    scene.history.append(stale_elsewhere)
    conversation = get_agent("conversation")
    conversation.write_config("character_knowledge", "perspective_filter", viewer)
    character = scene.character_data["Alice"]
    assert (conversation.rag_knowledge_viewer(character) is not None) is viewer
    current = conversation.rag_knowledge_filter(character)
    assert current is not None
    assert current(history_doc("A1"))
    assert current(message_doc(message.id))

    # another task edits the message while the retrieval awaits a query
    await asyncio.sleep(0)
    message.append_version("Alice: The key is gold.", "revision")

    assert not current(history_doc("A1"))
    assert not current(message_doc(message.id))


@pytest.mark.asyncio
async def test_checks_without_an_await_between_them_read_the_history_once(
    scene, monkeypatch
):
    standard_revision(scene)
    reads = count_reads(monkeypatch)
    check = RevisionCheck(scene)

    for i in range(30):
        check(history_doc(f"A{i}"))
    assert len(reads) == 1

    await asyncio.sleep(0)
    check(history_doc("A1"))
    assert len(reads) == 2


@pytest.mark.asyncio
async def test_multi_query_filters_after_the_last_query(scene, monkeypatch):
    standard_revision(scene)
    memory = get_agent("memory")
    fetched = []
    seen_at_filter = []

    async def fake_get(text, limit=10, **where):
        await asyncio.sleep(0)
        fetched.append(text)
        return [history_doc(f"{text}-A{i}") for i in range(3)]

    def recording_filter(document):
        seen_at_filter.append(len(fetched))
        return True

    monkeypatch.setattr(memory, "get", fake_get)
    with ActiveScene(scene):
        await memory.multi_query(
            ["q1", "", "q2", "q3"], iterate=3, filter=recording_filter
        )

    assert fetched == ["q1", "q2", "q3"]
    assert seen_at_filter == [3] * 9


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [500, 2500, 5000])
async def test_filter_work_does_not_grow_with_documents(scene, monkeypatch, count):
    standard_revision(scene)
    scene.history.extend(
        NarratorMessage(message=f"The tide turns {i}.") for i in range(count)
    )
    conversation = get_agent("conversation")
    character = scene.character_data["Alice"]
    digests = []
    digest = SceneMessage.revision_digest

    def counting(self):
        digests.append(self.id)
        return digest(self)

    monkeypatch.setattr(SceneMessage, "revision_digest", counting)

    current = conversation.rag_knowledge_filter(character)
    for _ in range(10):
        for i in range(30):
            current(history_doc(f"A{i}"))

    # one read of the history (one digest for each message with a revision
    # state) serves the build and all 300 documents
    assert len(digests) == count + 1


def test_retrieval_filter_rejects_with_the_check_it_was_given(scene):
    standard_revision(scene)
    check = RevisionCheck(scene)

    retrieval = KnowledgeIndex.from_scene(scene).retrieval_filter(scene, "Alice", check)

    assert retrieval.check is check
    assert retrieval.rejection(history_doc("A1")) == "stale"


@pytest.mark.asyncio
async def test_filter_with_a_viewer_reads_the_history_once_per_sweep(
    scene, monkeypatch
):
    _, _, message = standard_revision(scene)
    message.mark_revision_committed()
    reads = count_reads(monkeypatch)
    conversation = get_agent("conversation")
    conversation.write_config("character_knowledge", "perspective_filter", True)

    current = conversation.rag_knowledge_filter(scene.character_data["Alice"])
    # no knowledge edge: nothing to read before the first document
    assert len(reads) == 0

    await asyncio.sleep(0)
    for i in range(30):
        current(history_doc(f"A{i}"))
    assert len(reads) == 1
