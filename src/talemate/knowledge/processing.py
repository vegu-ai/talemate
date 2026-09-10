"""Completion barriers for operations that publish scene-analysis evidence."""

import asyncio
from contextvars import ContextVar
from functools import wraps
from inspect import signature
from weakref import WeakKeyDictionary

from talemate.exceptions import GenerationCancelled
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.status import LoadingStatus


_writers = WeakKeyDictionary()
_ancestors = ContextVar("evidence_writer_ancestors", default=())


def track_evidence_task(scene, task):
    """Register scheduled work before it gets its first event-loop turn."""
    if task is None:
        return
    writers = _writers.setdefault(scene, {})
    writers[task] = task
    task.add_done_callback(lambda done: writers.pop(done, None))


def evidence_writer(fn):
    """Track a writer's operation, including tasks returned by background dispatchers."""
    parameters = list(signature(fn).parameters)
    scene_index = parameters.index("scene") if "scene" in parameters else None

    @wraps(fn)
    async def wrapper(*args, **kwargs):
        owner = args[0] if args else kwargs[parameters[0]]
        if "scene" in kwargs:
            scene = kwargs["scene"]
        elif scene_index is not None and len(args) > scene_index:
            scene = args[scene_index]
        else:
            scene = owner.scene
        if scene is None:
            raise ValueError(f"Evidence writer {fn.__qualname__} requires a scene")
        writers = _writers.setdefault(scene, {})
        done = asyncio.get_running_loop().create_future()
        writers[done] = asyncio.current_task()
        token = _ancestors.set((*_ancestors.get(), done))
        cancel_sequence = scene.cancel_sequence
        try:
            result = await fn(*args, **kwargs)
            if isinstance(result, asyncio.Task):
                track_evidence_task(scene, result)
            return result
        except GenerationCancelled as exc:
            exc.by_user = exc.by_user or scene.cancel_sequence != cancel_sequence
            raise
        finally:
            _ancestors.reset(token)
            writers.pop(done, None)
            done.set_result(None)

    return wrapper


async def wait_for_evidence_writers(scene, *, agent, purpose="scene analysis"):
    """Drain existing writers and their follow-up work without launching requests."""
    if not character_knowledge_enabled(scene):
        return
    status = LoadingStatus(cancellable=True)
    cancel_sequence = scene.cancel_sequence
    cancelled = scene.interrupt_signal
    try:
        while True:
            scene.continue_actions()
            if scene.cancel_sequence != cancel_sequence:
                raise GenerationCancelled("action cancelled", by_user=True)
            if agent.scene is not scene:
                raise GenerationCancelled(
                    "Scene changed while waiting for scene analysis inputs"
                )
            pending = {
                done
                for done, owner in _writers.get(scene, {}).items()
                if not done.done()
                and owner is not asyncio.current_task()
                and done not in _ancestors.get()
            }
            if not pending:
                return
            status(f"Waiting for knowledge updates before {purpose}")
            # Observe completion without cancelling shared work or awaiting ourselves.
            await asyncio.wait(
                pending | {cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
    finally:
        status.done()
