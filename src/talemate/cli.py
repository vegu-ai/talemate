import argparse
import asyncio
import glob
import os

import structlog
from dotenv import load_dotenv

import talemate.instance as instance
from talemate import Actor, Character, Helper, Player, Scene
from talemate.agents import ConversationAgent
from talemate.client import OpenAIClient, TextGeneratorWebuiClient
from talemate.emit.console import Console
from talemate.load import (
    load_character_from_image,
    load_character_from_json,
    load_scene,
)
from talemate.remote.chub import CharacterHub

# Load env vars using dotenv
load_dotenv()

# Set up logging
log = structlog.get_logger("talemate.cli")


class DefaultClient:
    pass


async def run():
    parser = argparse.ArgumentParser(description="CLI for TaleMate")
    parser.add_argument("--load", type=str, help="Load scene.")
    parser.add_argument("--reset", action="store_true", help="Reset the scene.")
    parser.add_argument(
        "--load-char", type=str, help="Load character from a partial character name."
    )

    ai_client_choices = ["textgenwebui", "openai"]

    parser.add_argument(
        "--conversation-client",
        type=str,
        choices=ai_client_choices,
        help="Conversation AI client to use.",
        default=DefaultClient(),
    )
    parser.add_argument(
        "--summarizer-client",
        type=str,
        choices=ai_client_choices,
        help="Summarizer AI client to use.",
        default=DefaultClient(),
    )
    parser.add_argument(
        "--narrator-client",
        type=str,
        choices=ai_client_choices,
        help="Narrator AI client to use.",
        default=DefaultClient(),
    )
    # parser.add_argument("--editor-client", type=str, choices=ai_client_choices, help="Editor AI client to use.", default=DefaultClient())
    parser.add_argument(
        "--char-creator-client",
        type=str,
        choices=ai_client_choices,
        help="Character Creator AI client to use.",
        default=DefaultClient(),
    )
    parser.add_argument(
        "--client",
        type=str,
        choices=ai_client_choices,
        help="Default AI client to use.",
        default="textgenwebui",
    )

    parser.add_argument(
        "--textgenwebui-context",
        type=int,
        default=4096,
        help="Context size for TextGenWebUI client.",
    )
    parser.add_argument(
        "--textgenwebui-url",
        type=str,
        default=os.environ.get("CONVERSATION_API_URL"),
        help="URL for TextGenWebUI client. (defaults to CONVERSATION_API_URL environment variable)",
    )

    # Add new subparsers for chub command
    subparsers = parser.add_subparsers(dest="chub")

    # Add chub as a subparser
    chub_parser = subparsers.add_parser("chub", help="Interact with CharacterHub")

    # Add new subparsers for chub command
    chub_subparsers = chub_parser.add_subparsers(dest="chub_action")

    # chub search subcommand
    chub_search_parser = chub_subparsers.add_parser(
        "search", help="Search CharacterHub"
    )
    chub_search_parser.add_argument(
        "search_term", help="The search term to use for CharacterHub search"
    )

    args = parser.parse_args()

    await run_console_session(parser, args)


async def run_console_session(parser, args):
    console = Console()
    console.connect()

    # Setup AI Clients

    clients = {
        "conversation": args.conversation_client,
        "summarizer": args.summarizer_client,
        "narrator": args.narrator_client,
        "char_creator": args.char_creator_client,
    }

    default_client = None

    if "textgenwebui" in clients.values() or args.client == "textgenwebui":
        # Init the TextGeneratorWebuiClient with ConversationAgent and create an actor
        textgenwebui_api_url = args.textgenwebui_url

        text_generator_webui_client = TextGeneratorWebuiClient(
            textgenwebui_api_url, args.textgenwebui_context
        )
        log.info("initializing textgenwebui client", url=textgenwebui_api_url)

        for client_name, client_typ in clients.items():
            if client_typ == "textgenwebui" or (
                isinstance(client_typ, DefaultClient) and args.client == "textgenwebui"
            ):
                clients[client_name] = text_generator_webui_client

    if "openai" in clients.values() or args.client == "openai":
        openai_client = OpenAIClient()

        for client_name, client_typ in clients.items():
            if client_typ == "openai" or (
                isinstance(client_typ, DefaultClient) and args.client == "openai"
            ):
                log.info("initializing openai client")
                clients[client_name] = openai_client

    # Setup scene

    scene = Scene()

    # Init helper agents

    summarizer = instance.get_agent("summarizer", clients["summarizer"])
    narrator = instance.get_agent("narrator", clients["narrator"])
    creator = instance.get_agent("creator", clients["char_creator"])
    conversation = instance.get_agent("conversation", clients["conversation"])

    scene.add_helper(Helper(summarizer))
    scene.add_helper(Helper(narrator))
    scene.add_helper(Helper(creator))
    scene.add_helper(Helper(conversation))

    # contexter = ContextAgent(clients["contexter"])
    # scene.add_helper(Helper(contexter))

    USE_MEMORY = True
    if USE_MEMORY:
        memory_agent = instance.get_agent("memory", scene)
        scene.add_helper(Helper(memory_agent))

    # Check if the chub command is called
    if args.chub and args.chub_action:
        chub = CharacterHub()

        if args.chub_action == "search":
            results = chub.search(args.search_term)
            nodes = {}
            # Display up to 20 results to the user
            for i, node in enumerate(results):
                if i < 50:
                    print(f"{node['name']} (ID: {node['id']})", node["topics"])
                    nodes[str(node["id"])] = node
            print("Input the ID of the character you want to download:")
            node_id = input()

            node = nodes[node_id]
            print("node:", node)
            chub.download(node)
        return

    # Set up Test Character
    if args.load_char:
        character_directory = "./tales/characters"
        partial_char_name = args.load_char.lower()

        player = Player(Character("Elmer", "", "", color="cyan", gender="male"), None)
        scene.add_actor(player)

        # Search for a matching character filename
        for character_file in glob.glob(os.path.join(character_directory, "*.*")):
            file_name = os.path.basename(character_file)
            file_name_no_ext = os.path.splitext(file_name)[0].lower()

            if partial_char_name in file_name_no_ext:
                file_ext = os.path.splitext(character_file)[1].lower()
                image_format = file_ext.lstrip(".")

                # If a json file is found, use Character.load_from_json instead
                if file_ext == ".json":
                    test_character = load_character_from_json(character_file)
                    break
                else:
                    test_character = load_character_from_image(
                        character_file, image_format
                    )
                    break
        else:
            raise ValueError(
                f"No character file found with the provided partial name '{partial_char_name}'."
            )

        agent = ConversationAgent(clients.get("conversation"))
        actor = Actor(test_character, agent)

        # Add the TestCharacter actor to the scene
        scene.add_actor(actor)

    elif args.load:
        scene = load_scene(scene, args.load, clients["conversation"], reset=args.reset)
    else:
        log.error("No scene loaded. Please load a scene with the --load argument.")
        return

    # Continuously ask the user for input and send it to the actor's talk_to method

    await scene.start()


async def run_main():
    await run()


def main():
    asyncio.run(run_main())


if __name__ == "__main__":
    main()
