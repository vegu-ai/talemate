from talemate.knowledge.perspectives import select_character_view, view_staleness


def not_current(scene, reference, character) -> bool:
    """The view is stale or empty: a repair would rebuild it."""
    return view_staleness(scene, reference, character) is not None


def stale_text(scene, reference, character) -> str | None:
    """The text a reader gets from a view that is out of sync, or None."""
    view = select_character_view(scene, reference, character)
    assert view.stale and not_current(scene, reference, character)
    return view.text


def pending_messages(scene) -> list[int]:
    """Messages with a pending revision or views that are not current."""
    from talemate.agents.summarize.perceptions import perception_results_current
    from talemate.knowledge.revision_refresh import revision_requires_refresh

    return [
        message.id
        for message in scene.history
        if (
            message.revision_state is not None
            and revision_requires_refresh(scene, message)
        )
        or (
            message.knowledge is not None
            and not perception_results_current(scene, message)
        )
    ]
