"""
GPU memory helpers.

Kept framework-agnostic at the import boundary: torch is imported lazily so the
rest of the application keeps working on installs without a CUDA-enabled torch.
"""

import functools

__all__ = ["cuda_available", "release_cuda_cache"]


@functools.cache
def cuda_available() -> bool:
    """
    Whether torch reports a usable CUDA device.

    Importing torch costs ~1.2s and ~470MB, hence the deferred import. False
    when torch is absent or unusable, matching the rest of this module.
    """
    try:
        import torch
    except ImportError:
        return False

    return torch.cuda.is_available()


def release_cuda_cache() -> bool:
    """
    Return reserved-but-unused CUDA memory held by PyTorch's caching allocator
    back to the driver.

    PyTorch keeps the high-water-mark from the largest batch it has run (e.g. a
    full scene re-embed, or a TTS generation) reserved for reuse; it is only
    handed back to the driver on an explicit ``empty_cache()`` or process exit.
    This releases the idle portion. Resident model weights are live allocations,
    not idle cache, so they are unaffected.

    Returns True if a CUDA cache flush was performed, False otherwise (no torch,
    or no CUDA device).
    """
    if not cuda_available():
        return False

    import torch

    torch.cuda.empty_cache()
    return True
