import argparse
import asyncio
import os
import sys

import structlog
import websockets

import talemate.config
from talemate.server.api import websocket_endpoint

log = structlog.get_logger("talemate.server.run")


def run_server(args):
    """
    Run the talemate web server using the provided arguments.

    :param args: command line arguments parsed by argparse
    """

    import talemate.agents.custom
    import talemate.client.custom
    from talemate.world_state.templates import Collection
    from talemate.world_state.templates.defaults import create_defaults_if_empty_collection

    config = talemate.config.cleanup()
    
    if config.game.world_state.templates.state_reinforcement:
        Collection.create_from_legacy_config(config)

    start_server = websockets.serve(
        websocket_endpoint, args.host, args.port, max_size=2**23
    )
    asyncio.get_event_loop().run_until_complete(start_server)
    log.info("talemate backend started", host=args.host, port=args.port)
    asyncio.get_event_loop().run_forever()


def main():
    parser = argparse.ArgumentParser(description="talemate server")
    subparser = parser.add_subparsers(dest="command")

    # Add the 'runserver' command with its own arguments
    runserver_parser = subparser.add_parser(
        "runserver", help="Run the talemate api server"
    )
    runserver_parser.add_argument("--host", default="localhost", help="Hostname")
    runserver_parser.add_argument("--port", type=int, default=6000, help="Port")

    args = parser.parse_args()

    if args.command == "runserver":
        run_server(args)
    else:
        log.error("Unknown command", command=args.command)
        sys.exit(1)


if __name__ == "__main__":
    main()
