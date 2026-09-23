from contextlib import contextmanager

from talemate.agents.summarize.perceptions import resolve_perception_backlog
from talemate.emit.signals import handlers


@contextmanager
def answering(decision, frames):
    """Answer every perception backlog question with `decision`; record the frames."""

    def answer(emission):
        frames.append(emission.data)
        if decision is not None:
            resolve_perception_backlog(emission.data["request_id"], decision)

    handlers["perception_backlog"].connect(answer)
    try:
        yield
    finally:
        handlers["perception_backlog"].disconnect(answer)
