"""
Baseline snapshot tests for help agent prompt templates.

Captures the rendered prompt text passed to client.send_prompt() and compares
against stored baseline files. Run with --update-baselines to create/update.

The documentation index and doc tool results are stubbed with fixed data so
the baselines don't churn whenever the real documentation changes.
"""

import json
import re
from unittest.mock import AsyncMock, Mock, patch

import pytest

import talemate.agents.help.docs as help_docs
import talemate.agents.help.storage as help_storage
import talemate.instance as instance
from talemate.agents.help import HelpAgent
from talemate.agents.help.schema import HelpChatMessage

from ..conftest import mock_llm_client  # noqa: F401
from ..test_director_templates import mock_scene  # noqa: F401
from .conftest import capture_all_prompts, capture_prompt

AGENT = "help"

DOCS_INDEX = [
    {
        "path": "getting-started/index.md",
        "title": "Getting started",
        "summary": "Installation and first steps.",
    },
    {
        "path": "user-guide/agents/editor/settings.md",
        "title": "Settings",
        "summary": "Editor agent settings: revision methods and cleanup options.",
    },
]

UX_SNAPSHOT = {
    "active_tab": "settings",
    "open_drawers": ["scene"],
    "scene_active": False,
    "scene_environment": None,
    "app_settings_modal": {
        "tab": "settings",
        "page": "agents",
        "dirty": False,
        "agent": "editor",
        "mode": "global",
    },
    "templates_view": {
        "tab": "templates",
        "dirty": False,
        "selected": None,
        "template_type": None,
    },
    "app_ready": True,
    "waiting_for_input": False,
    "playthrough_active": False,
}

# The same view with a replay running: the mode's own section renders and the
# director console links drop out of the rules and the navigation list.
UX_SNAPSHOT_PLAYTHROUGH = {
    **UX_SNAPSHOT,
    "active_tab": "main",
    "scene_active": True,
    "scene_environment": "scene",
    "app_settings_modal": None,
    "playthrough_active": True,
}

READ_DOC_CALL = (
    "Let me look that up.\n"
    "```json\n"
    + json.dumps(
        {
            "function": "read_doc",
            "arguments": {"path": "user-guide/agents/editor/settings.md"},
        }
    )
    + "\n```"
)


@pytest.fixture
def help_agent(mock_llm_client, tmp_path, monkeypatch):  # noqa: F811
    """HelpAgent with a temporary chat store and a stubbed documentation index."""
    monkeypatch.setattr(help_storage, "HELP_CHATS_DIR", tmp_path)
    monkeypatch.setattr(help_storage, "HELP_CHATS_FILE", tmp_path / "help.json")
    monkeypatch.setattr(help_docs, "load_docs_index", lambda: DOCS_INDEX)
    monkeypatch.setattr(help_docs, "docs_available", lambda: True)
    monkeypatch.setattr(
        help_docs,
        "read_doc",
        lambda path: {
            "path": path,
            "url": help_docs.doc_url(path),
            "content": "# Settings\n\nStubbed documentation content.",
        },
    )
    agent = HelpAgent(client=mock_llm_client)
    agent.scene = None
    return agent


@pytest.fixture
def agent_registry(help_agent):
    """Fixed agent registry so the prompt's agent list is deterministic.

    Focal logs executed calls on the director agent, so that mock needs a
    real awaitable log_function_call.
    """
    director = Mock()
    director.log_function_call = AsyncMock()
    agents = {
        "conversation": Mock(),
        "creator": Mock(),
        "director": director,
        "editor": Mock(),
        "help": help_agent,
        "memory": Mock(),
        "narrator": Mock(),
        "summarizer": Mock(),
        "tts": Mock(),
        "visual": Mock(),
        "world_state": Mock(),
    }
    with patch.dict(instance.AGENTS, agents, clear=True):
        yield agents


class TestHelpBaselines:
    """Baseline tests for help agent chat prompts."""

    @pytest.mark.asyncio
    async def test_chat_send(self, help_agent, agent_registry, baseline_checker):
        """No scene loaded, direct answer without doc lookups."""
        chat = help_agent.chat_create()
        help_agent.client.send_prompt = AsyncMock(return_value="Here is your answer.")
        with patch.object(help_agent, "_chat_has_enough_for_title", return_value=False):
            await help_agent.chat_send(
                chat.id,
                "What do the different editor revision methods do?",
                ux_snapshot=UX_SNAPSHOT,
            )
        baseline_checker(capture_prompt(help_agent), AGENT, "chat_send")

    @pytest.mark.asyncio
    async def test_chat_send__settings_only(
        self, help_agent, agent_registry, baseline_checker
    ):
        """Settings granted, templates withheld - the mixed cell where a tool
        can be registered without its schema, or documented without existing."""
        help_agent.actions["permissions"].config["allow_settings_changes"].value = True

        chat = help_agent.chat_create()
        help_agent.client.send_prompt = AsyncMock(return_value="Here is your answer.")
        with patch.object(help_agent, "_chat_has_enough_for_title", return_value=False):
            await help_agent.chat_send(
                chat.id,
                "Turn off auto save for me.",
                ux_snapshot=UX_SNAPSHOT,
            )
        baseline_checker(capture_prompt(help_agent), AGENT, "chat_send__settings_only")

    @pytest.mark.asyncio
    async def test_chat_send__permissions_granted(
        self, help_agent, agent_registry, baseline_checker
    ):
        """Both permissions on - the write tools and the theme slot reference
        render, which the default-off cases above never show."""
        for key in ("allow_settings_changes", "allow_template_changes"):
            help_agent.actions["permissions"].config[key].value = True

        chat = help_agent.chat_create()
        help_agent.client.send_prompt = AsyncMock(return_value="Here is your answer.")
        with patch.object(help_agent, "_chat_has_enough_for_title", return_value=False):
            await help_agent.chat_send(
                chat.id,
                "Turn off auto save for me.",
                ux_snapshot=UX_SNAPSHOT,
            )
        baseline_checker(
            capture_prompt(help_agent), AGENT, "chat_send__permissions_granted"
        )

    @pytest.mark.asyncio
    async def test_chat_send__scene_aware(
        self,
        help_agent,
        agent_registry,
        mock_scene,  # noqa: F811
        baseline_checker,
    ):
        """Scene loaded and chat scene-aware - scene context section renders."""
        mock_scene.name = "the-forest-clearing"
        help_agent.scene = mock_scene
        chat = help_agent.chat_create()
        assert chat.scene_aware

        help_agent.client.send_prompt = AsyncMock(return_value="Here is your answer.")
        with patch.object(help_agent, "_chat_has_enough_for_title", return_value=False):
            await help_agent.chat_send(
                chat.id,
                "Who are the characters in my scene?",
                ux_snapshot=UX_SNAPSHOT,
            )
        baseline_checker(capture_prompt(help_agent), AGENT, "chat_send__scene_aware")

    @pytest.mark.asyncio
    async def test_chat_send__doc_lookup_final_round(
        self, help_agent, agent_registry, baseline_checker
    ):
        """
        First round performs a doc lookup; with the lookup-round limit at 1
        the follow-up renders the final-round instructions (no tools, answer
        now) with the doc result in the chat history.
        """
        help_agent.actions["chat"].config["doc_lookup_iterations"].value = 1
        chat = help_agent.chat_create()
        help_agent.client.send_prompt = AsyncMock(
            side_effect=[READ_DOC_CALL, "Here is your answer."]
        )
        with patch.object(help_agent, "_chat_has_enough_for_title", return_value=False):
            await help_agent.chat_send(
                chat.id,
                "What do the different editor revision methods do?",
                ux_snapshot=UX_SNAPSHOT,
            )
        baseline_checker(
            capture_all_prompts(help_agent), AGENT, "chat_send__doc_lookup_final_round"
        )

    @pytest.mark.asyncio
    async def test_chat_send__playthrough_active(
        self, help_agent, agent_registry, baseline_checker
    ):
        """A replay is running - the playthrough section renders and no
        `talemate://director-console` link is offered anywhere in the prompt."""
        chat = help_agent.chat_create()
        help_agent.client.send_prompt = AsyncMock(return_value="Here is your answer.")
        with patch.object(help_agent, "_chat_has_enough_for_title", return_value=False):
            await help_agent.chat_send(
                chat.id,
                "How do I open the director chat?",
                ux_snapshot=UX_SNAPSHOT_PLAYTHROUGH,
            )
        prompt = capture_prompt(help_agent)
        # sectioning sentence-cases the heading it renders
        assert "Playthrough mode is running" in prompt
        assert "talemate://director-console" not in prompt
        baseline_checker(prompt, AGENT, "chat_send__playthrough_active")

    @pytest.mark.asyncio
    async def test_chat_generate_title(
        self, help_agent, agent_registry, baseline_checker
    ):
        chat = help_agent.chat_create()
        await help_agent.chat_append_message(
            chat.id,
            HelpChatMessage(
                message="What do the editor revision methods do?", source="user"
            ),
        )
        help_agent.client.send_prompt = AsyncMock(
            return_value="<TITLE>Editor Revision Methods</TITLE>"
        )
        await help_agent.chat_generate_title(chat.id)
        baseline_checker(capture_prompt(help_agent), AGENT, "chat_generate_title")


PERMISSION_CELLS = [
    (False, False),
    (True, False),
    (False, True),
    (True, True),
]


@pytest.mark.parametrize("settings_on,templates_on", PERMISSION_CELLS)
@pytest.mark.asyncio
async def test_every_registered_tool_is_documented_and_no_other(
    help_agent, agent_registry, settings_on, templates_on
):
    """The prompt and the callback list have to agree in both directions: a
    tool the agent holds but was never told about is unusable, and one it was
    told about but does not hold wastes a round or is claimed as done."""
    config = help_agent.actions["permissions"].config
    config["allow_settings_changes"].value = settings_on
    config["allow_template_changes"].value = templates_on

    chat = help_agent.chat_create()
    help_agent.client.send_prompt = AsyncMock(return_value="Here is your answer.")
    with patch.object(help_agent, "_chat_has_enough_for_title", return_value=False):
        await help_agent.chat_send(chat.id, "What can you do?", ux_snapshot=UX_SNAPSHOT)

    prompt = capture_prompt(help_agent)
    documented = set(re.findall(r'"function": "([a-z_]+)"', prompt))
    registered = {
        callback.name
        for callback in (
            help_agent._chat_doc_callbacks()
            + help_agent._chat_settings_callbacks()
            + help_agent._chat_theme_callbacks()
            + help_agent._chat_template_callbacks()
        )
    }

    assert documented == registered
