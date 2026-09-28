print("Talemate starting.")
print("Startup may take a moment to initialize some dependencies, please be patient...")
import time

t_import_start = time.perf_counter()
import os

import logging
import logging.handlers
import structlog

import argparse
import asyncio
import signal
import sys

import websockets

import talemate.config  # noqa: F401
from talemate.version import VERSION
from talemate.path import LOGS_DIR
from talemate.environ import env_port, env_str
from talemate.server.shutdown import shutdown_server

print("Initialization time", time.perf_counter() - t_import_start)

TALEMATE_DEBUG = os.environ.get("TALEMATE_DEBUG", "0")
log_level = logging.DEBUG if TALEMATE_DEBUG == "1" else logging.INFO

# Configure file logging for errors when debug mode is enabled
if TALEMATE_DEBUG == "1":
    # Ensure logs directory exists
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Create rotating file handler for errors
    error_log_file = LOGS_DIR / "errors.log"
    file_handler = logging.handlers.RotatingFileHandler(
        error_log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.ERROR)

    # Create formatter for file output
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)

    # Configure root logger to use the file handler
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    root_logger.setLevel(log_level)

    print(f"Debug mode enabled - errors will be logged to: {error_log_file}")

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


async def log_stream(stream, log_func, on_started=None):
    started_emitted = False
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
            log_func("uvicorn", message=decoded_line)

        if (
            on_started
            and not started_emitted
            and "Application startup complete" in decoded_line
        ):
            started_emitted = True
            on_started()


async def run_frontend(host: str, port: int, on_started=None):
    if sys.platform == "win32":
        activate_cmd = ".\\.venv\\Scripts\\activate.bat"
        frontend_cmd = f"{activate_cmd} && uvicorn --host {host} --port {port} frontend_wsgi:application"
    else:
        frontend_cmd = f"/bin/bash -c 'source .venv/bin/activate && uvicorn --host {host} --port {port} frontend_wsgi:application'"
    frontend_cwd = None

    process = await asyncio.create_subprocess_shell(
        frontend_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=frontend_cwd,
        shell=True,
        preexec_fn=os.setsid if sys.platform != "win32" else None,
    )

    log.info(
        "talemate frontend started",
        host=host,
        port=port,
        server="uvicorn",
        process=process.pid,
    )

    try:
        stdout_task = asyncio.create_task(log_stream(process.stdout, log.info))
        stderr_task = asyncio.create_task(
            log_stream(process.stderr, log.error, on_started=on_started)
        )

        await asyncio.gather(stdout_task, stderr_task)
        await process.wait()
    finally:
        if process.returncode is None:
            if sys.platform == "win32":
                process.terminate()
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            await process.wait()


def run_server(args):
    """
    Run the talemate web server using the provided arguments.

    :param args: command line arguments parsed by argparse
    """

    import talemate.client.registry
    import talemate.agents.custom
    import talemate.client.custom
    import talemate.agents
    from talemate.agents.registry import get_agent_types
    from talemate.world_state.templates import Collection
    from talemate.prompts.overrides import get_template_overrides
    import talemate.client.system_prompts as system_prompts
    from talemate.emit.base import emit
    import talemate.agents.tts.voice_library as voice_library
    from talemate.changelog import ensure_changelogs_for_all_scenes
    from talemate.scene_assets import migrate_scene_assets_to_library
    from talemate.decisions.slot import configure_decision_service

    # import node libraries
    import talemate.game.engine.nodes.load_definitions
    import talemate.config
    import talemate.instance
    from talemate.server.api import websocket_endpoint
    from talemate.server.punkt import ensure_punkt

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

    # Get (or create) the asyncio event loop
    loop = asyncio.get_event_loop()

    loop.run_until_complete(voice_library.require_instance())
    loop.run_until_complete(talemate.instance.instantiate_clients())
    loop.run_until_complete(talemate.instance.instantiate_agents())
    configure_decision_service()

    # websockets>=12 requires ``websockets.serve`` to be called from within a
    # running event-loop (it uses ``asyncio.get_running_loop()`` internally).
    # Calling it directly, before the loop is running, raises
    # ``RuntimeError: no running event loop``.  To stay compatible with both old
    # and new versions we wrap the call in a small coroutine that we execute via
    # ``run_until_complete`` – this guarantees the loop is running when
    # ``serve`` is invoked.

    async def _start_websocket_server():
        return await websockets.serve(
            websocket_endpoint,
            args.host,
            args.port,
            max_size=50
            * 1024
            * 1024,  # 50MB limit to support import of scenes or cards with assets
        )

    # Start the websocket server and keep a reference so we can shut it down
    websocket_server = loop.run_until_complete(_start_websocket_server())

    # create task to ensure changelogs for all scenes exists
    loop.create_task(ensure_changelogs_for_all_scenes())

    # migrate scene assets to unified library.json files
    migrate_scene_assets_to_library()

    # start task to unstall punkt
    loop.create_task(ensure_punkt())

    def _on_frontend_started():
        if args.frontend_port == 8082:
            display_host = (
                "localhost" if args.frontend_host == "0.0.0.0" else args.frontend_host
            )
            separator = " " * 70
            log.info(separator)
            log.info("NOTICE: Talemate's default frontend port is now 8082 (was 8080) ")
            log.info("        to avoid conflicting with llama.cpp")
            log.info(
                f"        Open Talemate at: http://{display_host}:{args.frontend_port}"
            )
            log.info(
                "        To revert to the old port: set TALEMATE_FRONTEND_PORT=8080"
            )
            log.info(separator)

    if not args.backend_only:
        frontend_task = loop.create_task(
            run_frontend(
                args.frontend_host,
                args.frontend_port,
                on_started=_on_frontend_started,
            )
        )
    else:
        frontend_task = None

    log.info("talemate backend started", host=args.host, port=args.port)
    emit("talemate_started", data={"config": config})

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_server(
            loop, websocket_server, talemate.instance.get_agent("memory"), frontend_task
        )


def main():
    parser = argparse.ArgumentParser(description="talemate server")
    subparser = parser.add_subparsers(dest="command")

    # Add the 'runserver' command with its own arguments
    runserver_parser = subparser.add_parser(
        "runserver", help="Run the talemate api server"
    )
    runserver_parser.add_argument(
        "--host",
        default=env_str("TALEMATE_BACKEND_HOST", "localhost"),
        help="Hostname (env: TALEMATE_BACKEND_HOST)",
    )
    runserver_parser.add_argument(
        "--port",
        type=int,
        default=env_port("TALEMATE_BACKEND_PORT", 5050),
        help="Port (env: TALEMATE_BACKEND_PORT)",
    )
    runserver_parser.add_argument(
        "--backend-only", action="store_true", help="Run the backend only"
    )

    # frontend host and port
    runserver_parser.add_argument(
        "--frontend-host",
        default=env_str("TALEMATE_FRONTEND_HOST", "localhost"),
        help="Frontend Hostname (env: TALEMATE_FRONTEND_HOST)",
    )
    runserver_parser.add_argument(
        "--frontend-port",
        type=int,
        default=env_port("TALEMATE_FRONTEND_PORT", 8082),
        help="Frontend Port (env: TALEMATE_FRONTEND_PORT)",
    )

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
