import argparse
import asyncio
import os
import signal
import sys

import structlog
import websockets
import re

import talemate.config
from talemate.server.api import websocket_endpoint
from talemate.version import VERSION

log = structlog.get_logger("talemate.server.run")


STARTUP_TEXT = f"""

████████╗ █████╗ ██╗     ███████╗███╗   ███╗ █████╗ ████████╗███████╗
╚══██╔══╝██╔══██╗██║     ██╔════╝████╗ ████║██╔══██╗╚══██╔══╝██╔════╝
   ██║   ███████║██║     █████╗  ██╔████╔██║███████║   ██║   █████╗  
   ██║   ██╔══██║██║     ██╔══╝  ██║╚██╔╝██║██╔══██║   ██║   ██╔══╝  
   ██║   ██║  ██║███████╗███████╗██║ ╚═╝ ██║██║  ██║   ██║   ███████╗
   ╚═╝   ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝
v{VERSION}
"""

async def log_stream(stream, log_func):
    while True:
        line = await stream.readline()
        if not line:
            break
        decoded_line = line.decode().strip()
        
        # Check if the original line started with "INFO:" (Uvicorn startup messages)
        if decoded_line.startswith("INFO:"):
            # Use info level for Uvicorn startup messages
            log.info("uvicorn", message=decoded_line)
        else:
            # Use the provided log_func for other messages
            log_func("uvicron", message=decoded_line)

async def run_frontend(host: str = "localhost", port: int = 8080):
    if sys.platform == "win32":
        activate_cmd = ".\\talemate_env\\Scripts\\activate.bat"
        frontend_cmd = f"{activate_cmd} && uvicorn --host {host} --port {port} frontend_wsgi:application"
    else:
        frontend_cmd = f"/bin/bash -c 'source talemate_env/bin/activate && uvicorn --host {host} --port {port} frontend_wsgi:application'"
    frontend_cwd = None
        
    process = await asyncio.create_subprocess_shell(
        frontend_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=frontend_cwd,
        shell=True,
        preexec_fn=os.setsid if sys.platform != "win32" else None
    )
    
    log.info(f"talemate frontend started", host=host, port=port, server="uvicorn", process=process.pid)
    
    try:
        stdout_task = asyncio.create_task(log_stream(process.stdout, log.info))
        stderr_task = asyncio.create_task(log_stream(process.stderr, log.error))
        
        await asyncio.gather(stdout_task, stderr_task)
        await process.wait()
    finally:
        if process.returncode is None:
            if sys.platform == "win32":
                process.terminate()
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            await process.wait()

async def cancel_all_tasks(loop):
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    await asyncio.gather(*tasks, return_exceptions=True)

def run_server(args):
    """
    Run the talemate web server using the provided arguments.

    :param args: command line arguments parsed by argparse
    """

    import talemate.agents.custom
    import talemate.client.custom
    from talemate.world_state.templates import Collection
    from talemate.world_state.templates.defaults import (
        create_defaults_if_empty_collection,
    )

    config = talemate.config.cleanup()

    if config.game.world_state.templates.state_reinforcement:
        Collection.create_from_legacy_config(config)

    loop = asyncio.get_event_loop()
    
    start_server = websockets.serve(
        websocket_endpoint, args.host, args.port, max_size=2**23
    )
    
    loop.run_until_complete(start_server)
    
    if not args.backend_only:
        frontend_task = loop.create_task(run_frontend(args.frontend_host, args.frontend_port))
    else:
        frontend_task = None

    log.info("talemate backend started", host=args.host, port=args.port)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Shutting down...")
        
        if frontend_task:
            frontend_task.cancel()
        loop.run_until_complete(cancel_all_tasks(loop))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        log.info("Shutdown complete")

def main():
    parser = argparse.ArgumentParser(description="talemate server")
    subparser = parser.add_subparsers(dest="command")

    # Add the 'runserver' command with its own arguments
    runserver_parser = subparser.add_parser(
        "runserver", help="Run the talemate api server"
    )
    runserver_parser.add_argument("--host", default="localhost", help="Hostname")
    runserver_parser.add_argument("--port", type=int, default=6000, help="Port")
    runserver_parser.add_argument("--backend-only", action="store_true", help="Run the backend only")

    # frontend host and port
    runserver_parser.add_argument("--frontend-host", default="localhost", help="Frontend Hostname")
    runserver_parser.add_argument("--frontend-port", type=int, default=8080, help="Frontend Port")

    args = parser.parse_args()
    
    # wipe screen if backend only mode is not enabled
    # reason: backend only is run usually in dev mode and may be worth keeping the console output
    if not args.backend_only:
        # this needs to work on windows and linux
        os.system("cls" if os.name == "nt" else "clear")

    print(STARTUP_TEXT)

    if args.command == "runserver":
        run_server(args)
    else:
        log.error("Unknown command", command=args.command)
        sys.exit(1)


if __name__ == "__main__":
    main()