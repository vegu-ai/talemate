import argparse
import asyncio
import os
import signal
import sys

import structlog
import websockets

import talemate.config
from talemate.server.api import websocket_endpoint

log = structlog.get_logger("talemate.server.run")


async def start_frontend_process(command:str, cwd:str|None=None):
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        shell=True,
        preexec_fn=os.setsid if sys.platform != "win32" else None
    )
    return process

async def run_frontend(host: str = "localhost", port: int = 8080):
    if sys.platform == "win32":
        activate_cmd = ".\\talemate_env\\Scripts\\activate.bat"
    else:
        activate_cmd = "source talemate_env/bin/activate"
    frontend_cmd = f"{activate_cmd} && uvicorn --host {host} --port {port} frontend_wsgi:application"
    frontend_cwd = None
        
    process = await start_frontend_process(frontend_cmd, cwd=frontend_cwd)
    
    log.info(f"talemate frontend started", host=host, port=port, server="uvicorn", process=process.pid)
    
    try:
        await process.communicate()
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

    if args.command == "runserver":
        run_server(args)
    else:
        log.error("Unknown command", command=args.command)
        sys.exit(1)


if __name__ == "__main__":
    main()