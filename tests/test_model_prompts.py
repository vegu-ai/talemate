"""
Tests for LLM prompt template rendering (model_prompts.py).

Covers:
- Baseline rendering of built-in std/ templates (both Talemate-native and GGUF formats)
- GGUF-compatible variable availability
- std/user/ template CRUD operations
- Template selector listing (std_templates property)
- create_user_override with user/ prefix
- TemplateIdentifier detection
- Reasoning variable propagation
"""

import datetime
import os
import re
import textwrap

import huggingface_hub

import pytest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from talemate.client.model_prompts import (
    ModelPrompt,
    PromptSpec,
    STD_TEMPLATE_PATH,
    TEMPLATE_IDENTIFIERS,
)

BASELINES_DIR = (
    Path(__file__).parent / "data" / "prompts" / "baselines" / "model_prompts"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_render_context(
    system_message: str,
    prompt: str,
    reasoning_tokens: int = 0,
    spec: PromptSpec = None,
):
    """Build the full render context dict identical to ModelPrompt.__call__."""

    if "<|BOT|>" in prompt:
        user_message, coercion_message = prompt.split("<|BOT|>", 1)
    else:
        user_message = prompt
        coercion_message = ""

    if spec is None:
        spec = PromptSpec()

    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": user_message.strip()})
    if coercion_message:
        messages.append({"role": "assistant", "content": coercion_message})

    def _raise_exception(msg):
        raise Exception(msg)

    return {
        # Talemate native vars
        "system_message": system_message,
        "prompt": prompt.strip(),
        "user_message": user_message.strip(),
        "coercion_message": coercion_message,
        "set_response": lambda p, r: p,  # no-op for baselines
        "reasoning_tokens": reasoning_tokens,
        "spec": spec,
        # GGUF/llama.cpp compatible vars
        "messages": messages,
        "bos_token": "",
        "eos_token": "",
        "add_generation_prompt": True,
        "enable_thinking": reasoning_tokens > 0,
        "thinking_budget": reasoning_tokens,
        "strftime_now": lambda fmt: datetime.datetime.now().strftime(fmt),
        "raise_exception": _raise_exception,
    }


def render_std_template(
    template_name: str,
    system_message: str,
    prompt: str,
    reasoning_tokens: int = 0,
    spec: PromptSpec = None,
):
    """Render a template from STD_TEMPLATE_PATH with the full variable context."""
    env = Environment(loader=FileSystemLoader(STD_TEMPLATE_PATH))
    template = env.get_template(template_name)
    ctx = _build_render_context(system_message, prompt, reasoning_tokens, spec)
    return template.render(ctx)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def model_prompt():
    """Fresh ModelPrompt instance (no cached _env)."""
    return ModelPrompt()


@pytest.fixture
def baseline_checker(update_baselines):
    """Baseline checker for model_prompt tests."""

    def check(rendered: str, test_name: str):
        baseline_file = BASELINES_DIR / f"{test_name}.txt"
        if update_baselines:
            baseline_file.parent.mkdir(parents=True, exist_ok=True)
            baseline_file.write_text(rendered, encoding="utf-8")
            return
        if not baseline_file.exists():
            raise FileNotFoundError(
                f"Baseline not found: {baseline_file}\n"
                f"Run with --update-baselines to create it."
            )
        expected = baseline_file.read_text(encoding="utf-8")
        assert rendered == expected, (
            f"Rendered output does not match baseline: {baseline_file}\n"
            f"Run with --update-baselines to update."
        )

    return check


@pytest.fixture
def std_user_dir(tmp_path):
    """Provide a temporary std/user/ directory and patch the module constants.

    Yields the tmp dir path. Restores original paths on teardown.
    """
    import talemate.client.model_prompts as mp

    original_std_user = mp.STD_USER_TEMPLATE_PATH
    tmp_user = tmp_path / "std_user"
    tmp_user.mkdir()
    mp.STD_USER_TEMPLATE_PATH = str(tmp_user)
    yield tmp_user
    mp.STD_USER_TEMPLATE_PATH = original_std_user


@pytest.fixture
def user_override_dir(tmp_path):
    """Provide a temporary user/ override directory.

    Patches USER_TEMPLATE_PATH so create_user_override writes to tmp.
    """
    import talemate.client.model_prompts as mp

    original = mp.USER_TEMPLATE_PATH
    tmp_user = tmp_path / "user_overrides"
    tmp_user.mkdir()
    mp.USER_TEMPLATE_PATH = str(tmp_user)
    yield tmp_user
    mp.USER_TEMPLATE_PATH = original


@pytest.fixture
def model_prompt_with_std(tmp_path):
    """ModelPrompt whose env also searches STD_TEMPLATE_PATH and a tmp dir.

    Returns (ModelPrompt, tmp_dir) — write test templates into tmp_dir.
    """
    test_dir = tmp_path / "test_templates"
    test_dir.mkdir()
    mp = ModelPrompt()
    mp._env = Environment(
        loader=FileSystemLoader(
            [str(test_dir), STD_TEMPLATE_PATH],
        )
    )
    return mp, test_dir


@pytest.fixture
def gguf_template(tmp_path):
    """Create a GGUF-style chat template in a tmp directory.

    Returns (Environment, template_name, tmp_dir).
    """
    content = textwrap.dedent("""\
        {%- for message in messages -%}
        {%- if message['role'] == 'system' -%}
        <|system|>{{ message['content'] }}</s>
        {%- elif message['role'] == 'user' -%}
        <|user|>{{ message['content'] }}</s>
        {%- elif message['role'] == 'assistant' -%}
        <|assistant|>{{ message['content'] }}
        {%- endif -%}
        {%- endfor -%}
        {%- if add_generation_prompt -%}
        <|assistant|>
        {%- endif -%}
    """)
    fpath = tmp_path / "GGUFTest.jinja2"
    fpath.write_text(content)
    env = Environment(loader=FileSystemLoader(str(tmp_path)))
    return env, "GGUFTest.jinja2", tmp_path


@pytest.fixture
def gguf_thinking_template(tmp_path):
    """GGUF-style template that uses enable_thinking / thinking_budget."""
    content = textwrap.dedent("""\
        {%- for message in messages -%}
        {%- if message['role'] == 'system' -%}
        <|system|>{{ message['content'] }}</s>
        {%- elif message['role'] == 'user' -%}
        <|user|>{{ message['content'] }}</s>
        {%- elif message['role'] == 'assistant' -%}
        <|assistant|>{{ message['content'] }}
        {%- endif -%}
        {%- endfor -%}
        {%- if add_generation_prompt -%}
        <|assistant|>
        {%- if enable_thinking -%}
        <think>budget={{ thinking_budget }}</think>
        {%- endif -%}
        {%- endif -%}
    """)
    fpath = tmp_path / "GGUFThinkTest.jinja2"
    fpath.write_text(content)
    env = Environment(loader=FileSystemLoader(str(tmp_path)))
    return env, "GGUFThinkTest.jinja2", tmp_path


# ---------------------------------------------------------------------------
# Baseline rendering tests — built-in std/ templates
# ---------------------------------------------------------------------------


# Representative sample of std/ templates covering distinct structural patterns:
# - ChatML: simple multi-turn with special tokens
# - Llama3: header-based format
# - Alpaca: markdown-style instruction/response
# - Gemma4: reasoning with spec.set_spec + conditional blocks
# - Seed: complex reasoning budget logic
# - Qwen3.5: reasoning suppression via <think> tags
# - Muse-Glimmer: ATEM channel protocol with reasoning-dependent assistant open
_REPRESENTATIVE_TEMPLATES = [
    "ChatML.jinja2",
    "Llama3.jinja2",
    "Alpaca.jinja2",
    "Gemma4.jinja2",
    "Seed.jinja2",
    "Qwen3.5.jinja2",
    "Muse-Glimmer.jinja2",
]


class TestBuiltinTemplateBaselines:
    """Render representative std/ templates and compare against baselines."""

    SYSTEM_MSG = "You are a helpful storytelling assistant."
    PROMPT_WITH_BOT = "Write the next scene.<|BOT|>Sure, here is"
    PROMPT_WITHOUT_BOT = "Write the next scene."

    @pytest.mark.parametrize("template_name", _REPRESENTATIVE_TEMPLATES)
    def test_render_with_coercion(self, template_name, baseline_checker):
        rendered = render_std_template(
            template_name,
            self.SYSTEM_MSG,
            self.PROMPT_WITH_BOT,
        )
        safe_name = template_name.replace(".jinja2", "")
        baseline_checker(rendered, f"std__{safe_name}__coercion")

    @pytest.mark.parametrize("template_name", _REPRESENTATIVE_TEMPLATES)
    def test_render_without_coercion(self, template_name, baseline_checker):
        rendered = render_std_template(
            template_name,
            self.SYSTEM_MSG,
            self.PROMPT_WITHOUT_BOT,
        )
        safe_name = template_name.replace(".jinja2", "")
        baseline_checker(rendered, f"std__{safe_name}__no_coercion")

    @pytest.mark.parametrize(
        "template_name",
        ["Qwen3.5.jinja2", "Gemma4.jinja2", "Seed.jinja2"],
    )
    def test_render_with_reasoning(self, template_name, baseline_checker):
        rendered = render_std_template(
            template_name,
            self.SYSTEM_MSG,
            self.PROMPT_WITH_BOT,
            reasoning_tokens=1024,
        )
        safe_name = template_name.replace(".jinja2", "")
        baseline_checker(rendered, f"std__{safe_name}__reasoning")


# ---------------------------------------------------------------------------
# GGUF template rendering tests
# ---------------------------------------------------------------------------


class TestGGUFTemplateRendering:
    """Test that GGUF-format templates render correctly with the provided variables."""

    SYSTEM_MSG = "You are a helpful assistant."
    USER_MSG = "Tell me a story."
    COERCION = "Once upon a time"

    def test_gguf_basic_render(self, gguf_template, baseline_checker):
        """A GGUF template using messages/add_generation_prompt renders correctly."""
        env, tname, _ = gguf_template
        template = env.get_template(tname)

        messages = [
            {"role": "system", "content": self.SYSTEM_MSG},
            {"role": "user", "content": self.USER_MSG},
        ]
        rendered = template.render(
            messages=messages,
            bos_token="",
            eos_token="",
            add_generation_prompt=True,
            enable_thinking=False,
            thinking_budget=0,
        )
        baseline_checker(rendered, "gguf__basic")

    def test_gguf_with_coercion_message(self, gguf_template, baseline_checker):
        """GGUF template with assistant pre-fill in messages."""
        env, tname, _ = gguf_template
        template = env.get_template(tname)

        messages = [
            {"role": "system", "content": self.SYSTEM_MSG},
            {"role": "user", "content": self.USER_MSG},
            {"role": "assistant", "content": self.COERCION},
        ]
        rendered = template.render(
            messages=messages,
            bos_token="",
            eos_token="",
            add_generation_prompt=False,
            enable_thinking=False,
            thinking_budget=0,
        )
        baseline_checker(rendered, "gguf__with_coercion")

    def test_gguf_thinking_enabled(self, gguf_thinking_template, baseline_checker):
        """GGUF template using enable_thinking and thinking_budget."""
        env, tname, _ = gguf_thinking_template
        template = env.get_template(tname)

        messages = [
            {"role": "system", "content": self.SYSTEM_MSG},
            {"role": "user", "content": self.USER_MSG},
        ]
        rendered = template.render(
            messages=messages,
            bos_token="",
            eos_token="",
            add_generation_prompt=True,
            enable_thinking=True,
            thinking_budget=2048,
        )
        baseline_checker(rendered, "gguf__thinking_enabled")

    def test_gguf_thinking_disabled(self, gguf_thinking_template, baseline_checker):
        """Same template but thinking disabled."""
        env, tname, _ = gguf_thinking_template
        template = env.get_template(tname)

        messages = [
            {"role": "system", "content": self.SYSTEM_MSG},
            {"role": "user", "content": self.USER_MSG},
        ]
        rendered = template.render(
            messages=messages,
            bos_token="",
            eos_token="",
            add_generation_prompt=True,
            enable_thinking=False,
            thinking_budget=0,
        )
        baseline_checker(rendered, "gguf__thinking_disabled")

    def test_gguf_via_model_prompt(self, gguf_template, baseline_checker):
        """Render a GGUF template through ModelPrompt.__call__ to verify
        that both Talemate-native and GGUF variables are provided."""
        _, tname, tmp_dir = gguf_template
        mp = ModelPrompt()
        # Patch the env to also search our tmp dir
        mp._env = Environment(loader=FileSystemLoader([str(tmp_dir)]))
        rendered, _ = mp(
            model_name="__gguf_test__",
            system_message=self.SYSTEM_MSG,
            prompt=f"{self.USER_MSG}<|BOT|>{self.COERCION}",
            default_template=tname,
        )
        baseline_checker(rendered, "gguf__via_model_prompt")

    def test_gguf_via_model_prompt_with_reasoning(
        self, gguf_thinking_template, baseline_checker
    ):
        """GGUF template rendered through ModelPrompt with reasoning_tokens > 0."""
        _, tname, tmp_dir = gguf_thinking_template
        mp = ModelPrompt()
        mp._env = Environment(loader=FileSystemLoader([str(tmp_dir)]))
        rendered, _ = mp(
            model_name="__gguf_thinking_test__",
            system_message=self.SYSTEM_MSG,
            prompt=f"{self.USER_MSG}<|BOT|>",
            default_template=tname,
            reasoning_tokens=4096,
        )
        baseline_checker(rendered, "gguf__via_model_prompt_reasoning")


# ---------------------------------------------------------------------------
# GGUF variable availability tests (non-baseline, structural)
# ---------------------------------------------------------------------------


class TestGGUFVariables:
    """Verify GGUF-compatible variables are provided alongside Talemate vars."""

    def _render_probe(self, model_prompt_with_std, template_content, **call_kwargs):
        """Write a probe template and render it through ModelPrompt."""
        mp, test_dir = model_prompt_with_std
        probe = test_dir / "_probe.jinja2"
        probe.write_text(template_content)
        rendered, _ = mp(**call_kwargs, default_template="_probe.jinja2")
        return rendered

    def test_messages_structure(self, model_prompt_with_std):
        """The `messages` variable is a list of role/content dicts."""
        rendered = self._render_probe(
            model_prompt_with_std,
            "{{ messages | length }}:{{ messages[0]['role'] }}:{{ messages[1]['role'] }}",
            model_name="__test__",
            system_message="sys",
            prompt="user<|BOT|>asst",
        )
        assert rendered == "3:system:user"

    def test_enable_thinking_false_when_no_reasoning(self, model_prompt_with_std):
        """enable_thinking is False when reasoning_tokens=0."""
        rendered = self._render_probe(
            model_prompt_with_std,
            "thinking={{ enable_thinking }}|budget={{ thinking_budget }}",
            model_name="__test__",
            system_message="sys",
            prompt="user",
            reasoning_tokens=0,
        )
        assert rendered == "thinking=False|budget=0"

    def test_enable_thinking_true_when_reasoning(self, model_prompt_with_std):
        """enable_thinking is True when reasoning_tokens > 0."""
        rendered = self._render_probe(
            model_prompt_with_std,
            "thinking={{ enable_thinking }}|budget={{ thinking_budget }}",
            model_name="__test__",
            system_message="sys",
            prompt="user",
            reasoning_tokens=2048,
        )
        assert rendered == "thinking=True|budget=2048"

    def test_strftime_now_callable(self, model_prompt_with_std):
        """strftime_now is callable and returns a date string."""
        rendered = self._render_probe(
            model_prompt_with_std,
            "{{ strftime_now('%Y') }}",
            model_name="__test__",
            system_message="sys",
            prompt="user",
        )
        assert len(rendered) == 4
        assert rendered.isdigit()

    def test_bos_eos_tokens_empty(self, model_prompt_with_std):
        """bos_token and eos_token default to empty strings."""
        rendered = self._render_probe(
            model_prompt_with_std,
            "[{{ bos_token }}]--[{{ eos_token }}]",
            model_name="__test__",
            system_message="sys",
            prompt="user",
        )
        assert rendered == "[]--[]"

    def test_add_generation_prompt_true(self, model_prompt_with_std):
        """add_generation_prompt is True by default."""
        rendered = self._render_probe(
            model_prompt_with_std,
            "{{ add_generation_prompt }}",
            model_name="__test__",
            system_message="sys",
            prompt="user",
        )
        assert rendered == "True"

    def test_raise_exception_callable(self, model_prompt_with_std):
        """raise_exception raises when called."""
        mp, test_dir = model_prompt_with_std
        probe = test_dir / "_probe_raise.jinja2"
        probe.write_text("{{ raise_exception('boom') }}")
        with pytest.raises(Exception, match="boom"):
            mp(
                model_name="__test__",
                system_message="sys",
                prompt="user",
                default_template="_probe_raise.jinja2",
            )


# ---------------------------------------------------------------------------
# std/user/ CRUD tests
# ---------------------------------------------------------------------------


class TestStdUserCRUD:
    """Test CRUD operations on std/user/ templates."""

    def test_save_and_list(self, model_prompt, std_user_dir):
        """Saving a template makes it appear in list_std_user_templates."""
        model_prompt.save_std_user_template(
            "TestCRUD.jinja2", "hello {{ user_message }}"
        )
        templates = model_prompt.list_std_user_templates()
        names = [t["name"] for t in templates]
        assert "TestCRUD.jinja2" in names

    def test_save_content_roundtrip(self, model_prompt, std_user_dir):
        """Content is preserved through save + list."""
        model_prompt.save_std_user_template("RT.jinja2", "exact content")
        templates = model_prompt.list_std_user_templates()
        tmpl = next(t for t in templates if t["name"] == "RT.jinja2")
        assert tmpl["content"] == "exact content"

    def test_save_appends_extension(self, model_prompt, std_user_dir):
        """Extension is added if missing."""
        model_prompt.save_std_user_template("NoExt", "content")
        assert (std_user_dir / "NoExt.jinja2").exists()

    def test_get_user_content(self, model_prompt, std_user_dir):
        """get_std_template_content reads user templates via user/ prefix."""
        model_prompt.save_std_user_template("ReadMe.jinja2", "test content")
        content = model_prompt.get_std_template_content("user/ReadMe.jinja2")
        assert content == "test content"

    def test_get_builtin_content(self, model_prompt):
        """get_std_template_content reads built-in templates."""
        content = model_prompt.get_std_template_content("ChatML.jinja2")
        assert content is not None
        assert "<|im_start|>" in content

    def test_get_nonexistent_returns_none(self, model_prompt):
        """get_std_template_content returns None for missing templates."""
        assert model_prompt.get_std_template_content("nope.jinja2") is None

    def test_delete(self, model_prompt, std_user_dir):
        """Deleting a template removes it from disk."""
        model_prompt.save_std_user_template("ToDelete.jinja2", "bye")
        assert model_prompt.delete_std_user_template("ToDelete.jinja2")
        assert not (std_user_dir / "ToDelete.jinja2").exists()

    def test_delete_nonexistent(self, model_prompt, std_user_dir):
        """Deleting a nonexistent template returns False."""
        assert not model_prompt.delete_std_user_template("nope.jinja2")

    def test_list_builtin_excludes_user_dir(self, model_prompt, std_user_dir):
        """list_std_builtin_templates does not include user/ entries."""
        model_prompt.save_std_user_template("Hidden.jinja2", "nope")
        builtin = model_prompt.list_std_builtin_templates()
        names = [t["name"] for t in builtin]
        assert "Hidden.jinja2" not in names
        assert "ChatML.jinja2" in names

    def test_path_traversal_prevention(self, model_prompt, std_user_dir):
        """Filenames with path components are sanitized to basename only."""
        model_prompt.save_std_user_template("../../evil.jinja2", "pwned")
        assert (std_user_dir / "evil.jinja2").exists()
        assert not (std_user_dir.parent.parent / "evil.jinja2").exists()


# ---------------------------------------------------------------------------
# std_templates property tests
# ---------------------------------------------------------------------------


class TestStdTemplatesProperty:
    """Test the std_templates property that feeds the frontend selector."""

    def test_includes_builtin(self, model_prompt):
        """All built-in .jinja2 files appear in std_templates."""
        templates = model_prompt.std_templates
        assert "ChatML.jinja2" in templates
        assert "Llama3.jinja2" in templates

    def test_no_user_prefix_on_builtin(self, model_prompt):
        """Built-in templates don't have user/ prefix."""
        templates = model_prompt.std_templates
        for t in templates:
            if t.startswith("user/"):
                continue
            assert "/" not in t

    def test_user_templates_prefixed(self, model_prompt, std_user_dir):
        """User templates appear with user/ prefix."""
        model_prompt.save_std_user_template("Custom.jinja2", "hi")
        templates = model_prompt.std_templates
        assert "user/Custom.jinja2" in templates

    def test_user_templates_sorted_after_builtin(self, model_prompt, std_user_dir):
        """User templates come after all built-in templates."""
        model_prompt.save_std_user_template("AAA.jinja2", "first")
        templates = model_prompt.std_templates
        first_user_idx = next(
            i for i, t in enumerate(templates) if t.startswith("user/")
        )
        for t in templates[:first_user_idx]:
            assert not t.startswith("user/")


# ---------------------------------------------------------------------------
# create_user_override with user/ prefix
# ---------------------------------------------------------------------------


class TestCreateUserOverride:
    """Test that create_user_override handles both std/ and std/user/ sources."""

    def test_override_from_builtin(self, model_prompt, user_override_dir):
        """Standard override copies from std/."""
        dest = model_prompt.create_user_override("ChatML.jinja2", "my-model")
        assert os.path.isfile(dest)
        with open(dest) as f:
            assert "<|im_start|>" in f.read()

    def test_override_from_user(self, model_prompt, std_user_dir, user_override_dir):
        """Override with user/ prefix copies from std/user/."""
        model_prompt.save_std_user_template("MyFormat.jinja2", "custom content here")
        dest = model_prompt.create_user_override("user/MyFormat.jinja2", "my-model")
        assert os.path.isfile(dest)
        with open(dest) as f:
            assert f.read() == "custom content here"

    def test_cleaned_model_name_in_dest(self, model_prompt, user_override_dir):
        """Dest filename is the cleaned model name, not the template name."""
        dest = model_prompt.create_user_override("ChatML.jinja2", "org/MyModel:v1")
        basename = os.path.basename(dest)
        assert basename == "org__MyModel_v1.jinja2"


# ---------------------------------------------------------------------------
# TemplateIdentifier tests
# ---------------------------------------------------------------------------


class TestTemplateIdentifiers:
    """Test that template identifiers correctly detect their formats."""

    @pytest.mark.parametrize(
        "content,expected_template",
        [
            ("<|im_start|>system\n{{ system }}<|im_end|>", "ChatML"),
            (
                "<|start_header_id|>system<|end_header_id|>\n{{ sys }}<|eot_id|>",
                "Llama3",
            ),
            ("[INST] {{ sys }} {{ msg }} [/INST]", "Mistral"),
            ("### Instruction:\n{{ msg }}\n\n### Response:", "Alpaca"),
            (
                "<|system|>\n{{ sys }}</s>\n<|user|>\n{{ msg }}</s>\n<|assistant|>",
                "Zephyr",
            ),
            ("<|user|>\n{{ msg }}<|end|>\n<|assistant|>", "Phi-3"),
            (
                "<|start_of_role|>system<|end_of_role|>sys<|end_of_text|>",
                "Granite",
            ),
            (
                "GPT4 Correct System: sys<|end_of_turn|>"
                "GPT4 Correct User: msg<|end_of_turn|>"
                "GPT4 Correct Assistant:",
                "OpenChat",
            ),
            (
                "<|start|>system<|message|>sys<|eot|>"
                "<|start|>user<|message|>msg<|eot|>"
                "<|start|>assistant to=self<|message|>think<|eom|>",
                "Muse-Glimmer",
            ),
        ],
    )
    def test_identifier_detection(self, content, expected_template):
        """Each identifier correctly matches its format."""
        matched = None
        for cls in TEMPLATE_IDENTIFIERS:
            identifier = cls()
            if identifier(content):
                matched = identifier.template_str
                break
        assert matched == expected_template, (
            f"Expected {expected_template}, got {matched}"
        )

    def test_no_false_positive_on_harmony(self):
        """Harmony-style content (<|start|>/<|message|> without <|eot|>/<|eom|>) matches nothing."""
        harmony = (
            "<|start|>system<|message|>sys<|end|>"
            "<|start|>user<|message|>msg<|end|>"
            "<|start|>assistant<|channel|>final<|message|>"
        )
        for cls in TEMPLATE_IDENTIFIERS:
            assert not cls()(harmony)

    def test_no_false_positives_on_empty(self):
        """No identifier matches empty content."""
        for cls in TEMPLATE_IDENTIFIERS:
            assert not cls()("")

    def test_no_false_positives_on_plain_text(self):
        """No identifier matches plain text without special tokens."""
        plain = "Hello, this is just a regular message with no special tokens."
        for cls in TEMPLATE_IDENTIFIERS:
            assert not cls()(plain)


# ---------------------------------------------------------------------------
# PromptSpec tests
# ---------------------------------------------------------------------------


class TestPromptSpec:
    """Test PromptSpec metadata propagation during rendering."""

    def test_spec_template_set_after_render(self, model_prompt_with_std):
        """PromptSpec.template is set to the resolved template filename."""
        mp, test_dir = model_prompt_with_std
        # Write a minimal template
        (test_dir / "_spec_test.jinja2").write_text("{{ system_message }}")
        spec = PromptSpec()
        mp(
            model_name="__spec_test__",
            system_message="sys",
            prompt="user",
            default_template="_spec_test.jinja2",
            spec=spec,
        )
        assert spec.template == "_spec_test.jinja2"

    def test_spec_reasoning_pattern_set_by_template(self, model_prompt_with_std):
        """Templates like Gemma4 set spec.reasoning_pattern via set_spec."""
        mp, _ = model_prompt_with_std
        spec = PromptSpec()
        mp(
            model_name="__spec_test__",
            system_message="sys",
            prompt="user<|BOT|>",
            default_template="Gemma4.jinja2",
            reasoning_tokens=1024,
            spec=spec,
        )
        assert spec.reasoning_pattern is not None
        assert "channel" in spec.reasoning_pattern

    def test_spec_reasoning_pattern_seed(self, model_prompt_with_std):
        """Seed template always sets reasoning_pattern."""
        mp, _ = model_prompt_with_std
        spec = PromptSpec()
        mp(
            model_name="__spec_test__",
            system_message="sys",
            prompt="user<|BOT|>",
            default_template="Seed.jinja2",
            spec=spec,
        )
        assert spec.reasoning_pattern is not None
        assert "seed:think" in spec.reasoning_pattern

    def test_spec_reasoning_pattern_gpt_oss(self, model_prompt_with_std):
        """GPT-OSS template always sets reasoning_pattern."""
        mp, _ = model_prompt_with_std
        spec = PromptSpec()
        mp(
            model_name="__spec_test__",
            system_message="sys",
            prompt="user<|BOT|>",
            default_template="GPT-OSS.jinja2",
            spec=spec,
        )
        assert spec.reasoning_pattern is not None
        assert "final" in spec.reasoning_pattern
        assert "message" in spec.reasoning_pattern


# ---------------------------------------------------------------------------
# Muse-Glimmer template tests (ATEM channel protocol)
# ---------------------------------------------------------------------------


class TestMuseGlimmerTemplate:
    """Muse-Glimmer template renders the ATEM channel protocol correctly."""

    def _render(
        self,
        model_prompt_with_std,
        prompt="Write the next scene.",
        reasoning_tokens=0,
        spec=None,
    ):
        mp, _ = model_prompt_with_std
        return mp(
            model_name="__muse_glimmer_test__",
            system_message="You are a helpful storytelling assistant.",
            prompt=prompt,
            default_template="Muse-Glimmer.jinja2",
            reasoning_tokens=reasoning_tokens,
            spec=spec,
        )[0]

    def test_assistant_channel_prefilled_without_reasoning(self, model_prompt_with_std):
        """Without reasoning the user channel is prefilled so the response is clean."""
        rendered = self._render(model_prompt_with_std)
        assert rendered.startswith("<|start|>system<|message|>")
        assert '# Valid recipients: "self", "user".<|eot|>' in rendered
        assert rendered.endswith("<|start|>assistant to=user<|message|>")

    def test_assistant_open_with_reasoning(self, model_prompt_with_std):
        """With reasoning the assistant turn is left open for the reasoning channel."""
        spec = PromptSpec()
        rendered = self._render(model_prompt_with_std, reasoning_tokens=1024, spec=spec)
        assert rendered.endswith("<|start|>assistant")
        assert spec.reasoning_pattern is not None
        assert "to=user" in spec.reasoning_pattern
        assert spec.reasoning_validation_pattern is not None

    def test_no_spec_patterns_without_reasoning(self, model_prompt_with_std):
        spec = PromptSpec()
        self._render(model_prompt_with_std, spec=spec)
        assert spec.reasoning_pattern is None
        assert spec.reasoning_validation_pattern is None

    def test_coercion_in_user_channel(self, model_prompt_with_std):
        rendered = self._render(
            model_prompt_with_std, prompt="Write the next scene.<|BOT|>Sure, here is"
        )
        assert rendered.endswith("<|start|>assistant to=user<|message|>Sure, here is")

    def test_reasoning_pattern_strips_both_response_shapes(self, model_prompt_with_std):
        """The strip pattern cleans reasoned and direct ATEM responses alike."""
        spec = PromptSpec()
        self._render(model_prompt_with_std, reasoning_tokens=1024, spec=spec)
        reasoned = (
            " to=self<|message|>thinking<|eom|>"
            "<|start|>assistant to=user<|message|>The answer."
        )
        direct = " to=user<|message|>The answer."
        for response in (reasoned, direct):
            match = re.search(spec.reasoning_pattern, response, re.DOTALL)
            assert match is not None
            assert response.replace(match.group(0), "") == "The answer."
            assert re.search(spec.reasoning_validation_pattern, response, re.DOTALL)

    def test_truncated_reasoning_hits_error_path(self, model_prompt_with_std):
        """Mid-reasoning truncation validates as reasoned but fails the strip,
        surfacing ReasoningResponseError instead of leaking raw reasoning."""
        spec = PromptSpec()
        self._render(model_prompt_with_std, reasoning_tokens=1024, spec=spec)
        truncated = " to=self<|message|>thinking cut off mid"
        assert re.search(spec.reasoning_validation_pattern, truncated, re.DOTALL)
        assert not re.search(spec.reasoning_pattern, truncated, re.DOTALL)

    def test_reasoning_baseline(self, model_prompt_with_std, baseline_checker):
        """Reasoning render without coercion leaves the assistant turn open."""
        rendered = self._render(model_prompt_with_std, reasoning_tokens=1024)
        baseline_checker(rendered, "std__Muse-Glimmer__reasoning")

    @pytest.mark.parametrize(
        "reasoning_tokens,strength",
        [(0, "low"), (1024, "low"), (2048, "medium"), (8192, "high")],
    )
    def test_reasoning_strength_buckets(
        self, model_prompt_with_std, reasoning_tokens, strength
    ):
        rendered = self._render(
            model_prompt_with_std, reasoning_tokens=reasoning_tokens
        )
        assert f"Reasoning strength: {strength}." in rendered


# ---------------------------------------------------------------------------
# HF template suggestion file-priority tests
# ---------------------------------------------------------------------------


class TestQueryHFTemplateSuggestion:
    """query_hf_for_prompt_template_suggestion checks files in priority order."""

    ATEM_CONTENT = (
        "<|start|>system<|message|>sys<|eot|>"
        "<|start|>user<|message|>msg<|eot|>"
        "<|start|>assistant to=self<|message|>think<|eom|>"
    )

    def _stub_hf(self, model_prompt, monkeypatch, downloads):
        class _FakeModel:
            id = "some-org/some-model"

        monkeypatch.setattr(
            huggingface_hub.HfApi,
            "list_models",
            lambda *args, **kwargs: iter([_FakeModel()]),
        )
        monkeypatch.setattr(
            model_prompt,
            "_download_hf_file",
            lambda repo_id, filename, revision: downloads.get(filename),
        )

    def test_jinja_fallback(self, model_prompt, monkeypatch):
        """chat_template.jinja is checked when chat_template.jinja2 is missing."""
        self._stub_hf(
            model_prompt,
            monkeypatch,
            {
                "chat_template.jinja2": None,
                "chat_template.jinja": self.ATEM_CONTENT,
                "README.md": None,
                "tokenizer_config.json": None,
            },
        )
        assert (
            model_prompt.query_hf_for_prompt_template_suggestion("some-model")
            == "Muse-Glimmer.jinja2"
        )

    def test_jinja2_takes_priority(self, model_prompt, monkeypatch):
        """chat_template.jinja2 wins over chat_template.jinja when both exist."""
        self._stub_hf(
            model_prompt,
            monkeypatch,
            {
                "chat_template.jinja2": "<|im_start|>system\n{{ sys }}<|im_end|>",
                "chat_template.jinja": self.ATEM_CONTENT,
                "README.md": None,
                "tokenizer_config.json": None,
            },
        )
        assert (
            model_prompt.query_hf_for_prompt_template_suggestion("some-model")
            == "ChatML.jinja2"
        )
