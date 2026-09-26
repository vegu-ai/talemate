import os
import signal
import sys
import threading
import time


def enforce_deadline(pid: int, deadline: float, timeout: float, parent_exited):
    if parent_exited.wait(max(0, deadline - time.monotonic())):
        return
    try:
        os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    except OSError:
        os._exit(0)
    try:
        os.write(
            2,
            (
                f"Shutdown exceeded {timeout:g} seconds; forcing process exit. "
                "Unfinished background work will be abandoned.\n"
            ).encode(),
        )
    finally:
        os._exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    parent_exited = threading.Event()
    watchdog = threading.Thread(
        target=enforce_deadline,
        args=(int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), parent_exited),
        daemon=True,
    )
    watchdog.start()
    # EOF also disarms the watchdog when the parent exits before the deadline.
    sys.stdin.buffer.read(1)
    parent_exited.set()
    # Killing the parent closes stdin; allow the diagnostic to finish without
    # leaving the watchdog stuck on a stalled stderr reader.
    watchdog.join(timeout=1)
