import copy
import random
from urllib.parse import urljoin as _urljoin

__all__ = ["urljoin"]

def urljoin(base, *args):
    base = f"{base.rstrip('/')}/"
    return _urljoin(base, *args)