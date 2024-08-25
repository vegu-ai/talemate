import asyncio
import sys
import os
import argparse
import signal

def safe_decode(byte_string):
    try:
        return byte_string.decode('utf-8')
    except UnicodeDecodeError:
        return byte_string.decode('utf-8', errors='replace')

async def read_stream(stream, prefix):
    while True:
        line = await stream.readline()
        if not line:
            break
        print(f"{prefix}: {safe_decode(line).strip()}")

async def start_process(command, cwd=None, prefix=""):
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        shell=True,
        preexec_fn=os.setsid if sys.platform != "win32" else None
    )
    print(f"Started {prefix} process")
    return process

async def terminate_process(process, prefix):
    try:
        if sys.platform != "win32":
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:
            process.terminate()
        await asyncio.wait_for(process.wait(), timeout=5.0)
    except ProcessLookupError:
        print(f"{prefix} process has already exited")
    except asyncio.TimeoutError:
        print(f"{prefix} process did not terminate in time, forcing...")
        if sys.platform != "win32":
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
    except Exception as e:
        print(f"Error terminating {prefix} process: {e}")

async def main(dev_mode):
    # Start the frontend process
    if dev_mode:
        frontend_cmd = "npm run serve"
        frontend_cwd = "talemate_frontend"
    else:
        if sys.platform == "win32":
            activate_cmd = ".\\talemate_env\\Scripts\\activate.bat"
        else:
            activate_cmd = "source talemate_env/bin/activate"
        frontend_cmd = f"{activate_cmd} && uvicorn --host 0.0.0.0 --port 8080 --workers 4 frontend_wsgi:application"
        frontend_cwd = None

    frontend_process = await start_process(frontend_cmd, cwd=frontend_cwd, prefix="Frontend")

    # Start the backend process
    if sys.platform == "win32":
        activate_cmd = ".\\talemate_env\\Scripts\\activate.bat"
        backend_cmd = f"{activate_cmd} && python src\\talemate\\server\\run.py runserver --host 0.0.0.0 --port 5050"
    else:
        activate_cmd = "source talemate_env/bin/activate"
        backend_cmd = f"{activate_cmd} && python src/talemate/server/run.py runserver --host 0.0.0.0 --port 5050"
    
    backend_process = await start_process(backend_cmd, prefix="Backend")

    async def signal_handler(sig, frame):
        print("Stopping processes...")
        await terminate_process(frontend_process, "Frontend")
        await terminate_process(backend_process, "Backend")

    if sys.platform == "win32":
        signal.signal(signal.SIGINT, lambda s, f: asyncio.create_task(signal_handler(s, f)))
        signal.signal(signal.SIGTERM, lambda s, f: asyncio.create_task(signal_handler(s, f)))
    else:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(signal_handler(s, None)))

    try:
        # Read output from both processes concurrently
        await asyncio.gather(
            read_stream(frontend_process.stdout, "Frontend OUT"),
            read_stream(frontend_process.stderr, "Frontend ERR"),
            read_stream(backend_process.stdout, "Backend OUT"),
            read_stream(backend_process.stderr, "Backend ERR")
        )

        # Wait for both processes to complete
        await asyncio.gather(
            frontend_process.wait(),
            backend_process.wait()
        )
    except asyncio.CancelledError:
        pass
    finally:
        # Terminate both processes
        await signal_handler(None, None)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Talemate server")
    parser.add_argument("--dev", action="store_true", help="Run in development mode")
    args = parser.parse_args()

    asyncio.run(main(args.dev))