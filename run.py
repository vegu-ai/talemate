import asyncio
import sys
import os

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

async def main():
    # Start the frontend process
    frontend_cmd = "npm run serve"
    frontend_process = await start_process(frontend_cmd, cwd="talemate_frontend", prefix="Frontend")

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
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Keyboard interrupt received. Exiting...")