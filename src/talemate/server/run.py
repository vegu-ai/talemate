import os

import logging
import structlog

import argparse
import asyncio
import signal
import sys

import websockets
import re

import talemate.config
from talemate.server.api import websocket_endpoint
from talemate.version import VERSION

TALEMATE_DEBUG = os.environ.get("TALEMATE_DEBUG", "0")
log_level = logging.DEBUG if TALEMATE_DEBUG == "1" else logging.INFO

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(log_level),
)


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

async def install_punkt():
    import nltk
    
    log.info("Downloading NLTK punkt tokenizer")
    await asyncio.get_event_loop().run_in_executor(None, nltk.download, "punkt")
    await asyncio.get_event_loop().run_in_executor(None, nltk.download, "punkt_tab")
    log.info("Download complete")

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

async def run_frontend(host: str = "0.0.0.0", port: int = 8080):
    # Use uv run to execute uvicorn
    frontend_cmd = f"uv run uvicorn --host {host} --port {port} frontend_wsgi:application"
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

async def async_run_server(args):
    """
    Run the talemate web server using the provided arguments.

    :param args: command line arguments parsed by argparse
    """

    import talemate.agents.custom
    import talemate.client.custom
    import talemate.agents
    from talemate.agents.registry import get_agent_types
    from talemate.world_state.templates import Collection
    from talemate.prompts.overrides import get_template_overrides
    import talemate.client.system_prompts as system_prompts
    
    # import node libraries
    import talemate.game.engine.nodes.load_definitions


    config = talemate.config.cleanup()

    if config.game.world_state.templates.state_reinforcement:
        Collection.create_from_legacy_config(config)
        
    # pre-cache system prompts
    system_prompts.cache_all()
    
    for agent_type in get_agent_types():
        template_overrides = get_template_overrides(agent_type)
        for template_override in template_overrides:
            if not template_override.override_newer:
                continue
            log.warning(
                "Outdated Template Override",
                agent_type=agent_type,
                template=template_override.template_name,
                age=template_override.age_difference,
            )
    
    # Create a wrapper that handles the new websockets API
    async def websocket_handler(websocket):
        await websocket_endpoint(websocket, websocket.path)
    
    server = await websockets.serve(
        websocket_handler, args.host, args.port, max_size=2**23
    )
    
    # start task to install punkt
    asyncio.create_task(install_punkt())
    
    if not args.backend_only:
        frontend_task = asyncio.create_task(run_frontend(args.frontend_host, args.frontend_port))
    else:
        frontend_task = None

    log.info("talemate backend started", host=args.host, port=args.port)
    
    try:
        await asyncio.Future()  # run forever
    except asyncio.CancelledError:
        pass
    finally:
        log.info("Shutting down...")
        
        if frontend_task:
            frontend_task.cancel()
            try:
                await frontend_task
            except asyncio.CancelledError:
                pass
        
        server.close()
        await server.wait_closed()
        log.info("Shutdown complete")

def run_server(args):
    """
    Wrapper to run the async server function.
    """
    try:
        asyncio.run(async_run_server(args))
    except KeyboardInterrupt:
        pass

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
    runserver_parser.add_argument("--frontend-host", default="0.0.0.0", help="Frontend Hostname")
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