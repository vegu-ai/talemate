import asyncio

import nltk
import structlog
from nltk.tokenize.punkt import PunktTokenizer

log = structlog.get_logger("talemate.server.punkt")

PUNKT_PACKAGES = ("punkt", "punkt_tab")


def punkt_available() -> bool:
    # Loading the tokenizer, rather than nltk.data.find, catches data that is
    # missing or unreadable (find resolves the package directory without reading
    # its files). It cannot catch a file that is merely short: a truncated
    # abbrev_types.txt still parses and loads.
    try:
        PunktTokenizer("english")
    except Exception:
        log.debug("NLTK punkt tokenizer data is missing or damaged", exc_info=True)
        return False
    return True


async def ensure_punkt() -> None:
    if punkt_available():
        log.debug("NLTK punkt tokenizer already available")
        return

    log.info("Downloading NLTK punkt tokenizer")
    loop = asyncio.get_event_loop()
    for package in PUNKT_PACKAGES:
        await loop.run_in_executor(None, nltk.download, package)
    log.info("Download complete")
