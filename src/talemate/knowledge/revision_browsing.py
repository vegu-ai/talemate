from contextlib import contextmanager
from contextvars import ContextVar


defer_derived_jobs = ContextVar("defer_derived_jobs", default=False)


@contextmanager
def defer_revision_work():
    """Invalidate changed evidence immediately, but leave derived jobs for keep/catch-up."""
    token = defer_derived_jobs.set(True)
    try:
        yield
    finally:
        defer_derived_jobs.reset(token)
