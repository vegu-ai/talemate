import asyncio
import sys
import os
import argparse

async def read_stream(stream, prefix):
    while True:
        line = await stream.readline()
        if not line:
            break
        print(f"{prefix}: {line.decode().strip()}")

async def run_command(command, cwd=None, prefix=""):
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        shell=True
    )
    
    await asyncio.gather(
        read_stream(process.stdout, f"{prefix} OUT"),
        read_stream(process.stderr, f"{prefix} ERR")
    )
    
    return process

async def start_process(command, cwd=None, prefix=""):
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        shell=True
    )
    print(f"Started {prefix} process")
    return process

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
        frontend_cmd = f"{activate_cmd} && gunicorn --bind 0.0.0.0:8080 frontend_wsgi:application"
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

    # Read output from both processes concurrently
    await asyncio.gather(
        read_stream(frontend_process.stdout, "Frontend OUT"),
        read_stream(frontend_process.stderr, "Frontend ERR"),
        read_stream(backend_process.stdout, "Backend OUT"),
        read_stream(backend_process.stderr, "Backend ERR")
    )

    try:
        # Wait for both processes to complete
        await asyncio.gather(
            frontend_process.wait(),
            backend_process.wait()
        )
    except asyncio.CancelledError:
        print("Stopping processes...")
    finally:
        # Terminate both processes
        frontend_process.terminate()
        backend_process.terminate()
        await frontend_process.wait()
        await backend_process.wait()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Talemate server")
    parser.add_argument("--dev", action="store_true", help="Run in development mode")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.dev))
    except KeyboardInterrupt:
        print("Keyboard interrupt received. Exiting...")