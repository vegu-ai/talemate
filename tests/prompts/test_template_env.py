"""
Unit tests for ``Prompt.template_env`` search-path construction.

These tests pin the scene-level directories that get appended to the Jinja2
loader's ``searchpath`` — including the ``{template_dir}/scene/`` directory
where the prompt-manager UI stores templates created under the ``scene``
agent prefix. Without that directory in the search path, those templates
would not be resolvable from runtime ``{% include %}`` calls when the
active agent_type is anything other than ``"scene"``.
"""

import pytest

from talemate.context import active_scene
from talemate.prompts.base import Prompt

from ._groups_test_helpers import make_template_dir_scene


@pytest.fixture
def scene_with_template_dir(tmp_path):
    """Activate a real Scene whose ``template_dir`` is an isolated tmp dir."""
    scene = make_template_dir_scene(template_dir=str(tmp_path))
    token = active_scene.set(scene)
    try:
        yield scene
    finally:
        active_scene.reset(token)


def _searchpath_for(agent_type: str) -> list[str]:
    """Render the Jinja2 search path the loader would use for ``agent_type``."""
    prompt = Prompt.get(f"{agent_type}.dummy")
    env = prompt.template_env()
    return list(env.loader.searchpath)


class TestSceneTemplateSearchPath:
    """The scene template directories appended to the Jinja2 searchpath."""

    def test_scene_subdir_included_when_present(
        self, tmp_path, scene_with_template_dir
    ):
        """``{template_dir}/scene/`` is added when the directory exists, even
        though the active agent_type is ``"narrator"`` (not ``"scene"``).

        This is the regression guard for prompt-manager-created templates that
        sit under the ``scene`` agent prefix.
        """
        scene_subdir = tmp_path / "scene"
        scene_subdir.mkdir()

        searchpath = _searchpath_for("narrator")

        assert str(scene_subdir) in searchpath

    def test_scene_subdir_omitted_when_missing(self, tmp_path, scene_with_template_dir):
        """Missing ``scene/`` dir is silently skipped (no stray path entries)."""
        # tmp_path exists but has no `scene/` subdirectory
        searchpath = _searchpath_for("narrator")

        assert str(tmp_path / "scene") not in searchpath

    def test_agent_subdir_still_included(self, tmp_path, scene_with_template_dir):
        """The agent-specific subdir continues to be added (no regression)."""
        agent_subdir = tmp_path / "narrator"
        agent_subdir.mkdir()
        (tmp_path / "scene").mkdir()

        searchpath = _searchpath_for("narrator")

        assert str(agent_subdir) in searchpath

    def test_flat_template_dir_still_included(self, tmp_path, scene_with_template_dir):
        """The flat ``template_dir`` root is still appended (backward compat)."""
        (tmp_path / "scene").mkdir()

        searchpath = _searchpath_for("narrator")

        assert str(tmp_path) in searchpath

    def test_scene_subdir_resolves_template_for_other_agent(
        self, tmp_path, scene_with_template_dir
    ):
        """A template stored at ``{template_dir}/scene/foo.jinja2`` resolves
        through the env loader when the active agent_type is unrelated.

        This is the end-to-end behavior the search-path fix enables: the
        prompt-manager writes scene-group templates under ``scene/`` using
        the ``scene`` agent prefix; runtime renders happen under arbitrary
        agent types (narrator, director, …) and must still find them.
        """
        scene_subdir = tmp_path / "scene"
        scene_subdir.mkdir()
        (scene_subdir / "foo.jinja2").write_text("scene-group body")

        prompt = Prompt.get("narrator.dummy")
        env = prompt.template_env()
        # ``get_template`` walks the searchpath and raises if not found.
        template = env.get_template("foo.jinja2")
        assert template.render() == "scene-group body"

    def test_search_path_ordering(self, tmp_path, scene_with_template_dir):
        """Agent subdir is searched before the scene-group subdir, which is
        searched before the flat root — so a template that exists in multiple
        locations resolves from the highest-priority one.
        """
        agent_subdir = tmp_path / "narrator"
        scene_subdir = tmp_path / "scene"
        agent_subdir.mkdir()
        scene_subdir.mkdir()

        searchpath = _searchpath_for("narrator")
        agent_idx = searchpath.index(str(agent_subdir))
        scene_idx = searchpath.index(str(scene_subdir))
        flat_idx = searchpath.index(str(tmp_path))

        assert agent_idx < scene_idx < flat_idx


class TestSceneTemplateSearchPathNoScene:
    """Without an active scene, no scene-template dirs should appear."""

    def test_no_scene_omits_scene_dirs(self, tmp_path):
        """No active scene → no ``scene/`` dir appears in the search path."""
        prompt = Prompt.get("narrator.dummy")
        env = prompt.template_env()
        searchpath = list(env.loader.searchpath)

        # tmp_path was never registered as a scene template_dir
        assert str(tmp_path / "scene") not in searchpath
        assert str(tmp_path) not in searchpath
