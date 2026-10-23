import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import structlog

log = structlog.get_logger(__name__)

SHUTDOWN_TIMEOUT = 5.0


async def drain_server(loop, websocket_server, frontend_task=None):
    if frontend_task:
        frontend_task.cancel()
    websocket_server.close()
    await websocket_server.wait_closed()

    tasks = [
        task for task in asyncio.all_tasks(loop) if task is not asyncio.current_task()
    ]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await loop.shutdown_asyncgens()
    await loop.shutdown_default_executor()


def shutdown_server(
    loop, websocket_server, memory, frontend_task=None, *, timeout=SHUTDOWN_TIMEOUT
):
    # A native executor call can hold the GIL, so a Python watchdog thread
    # inside this process cannot enforce the deadline.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        reader, writer = os.pipe()
        try:
            subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(Path(__file__).with_name("shutdown_watchdog.py")),
                    str(os.getpid()),
                    str(time.monotonic() + timeout),
                    str(timeout),
                ],
                stdin=reader,
                stdout=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if os.name == "nt"
                else 0,
            )
        except OSError:
            os.close(writer)
            raise
        finally:
            os.close(reader)
        # Keep the raw writer open until OS process teardown. A Python file
        # finalizer could disarm the watchdog before a native destructor stalls.
    except OSError as exc:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        log.error(
            "Cannot start shutdown watchdog; continuing without a deadline; "
            "press Ctrl+C again to force exit",
            error=str(exc),
        )
    log.info("Shutting down...")
    try:
        memory.refuse_new_memory_work()
        loop.run_until_complete(drain_server(loop, websocket_server, frontend_task))
        loop.close()
        log.info("Shutdown complete")
    except BaseException as exc:
        log.error("Shutdown failed; forcing process exit", error=str(exc))
        os._exit(1)
