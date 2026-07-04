"""Unit tests for talemate.scene_assets.

Covers pydantic schemas (CoverBBox, AssetMeta, AssetSelectionContext, Asset),
SceneAssets CRUD against library.json, asset transfer/dedupe, MIME helpers,
search/select, cover-image and avatar setters, cleanup helpers,
add_asset_from_image_data / file path / generation response, and
migrate_scene_assets_to_library.

LLM/vision/websocket-event paths are intentionally NOT exercised here.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image

import talemate.scene_assets as scene_assets
from talemate.scene_assets import (
    Asset,
    AssetMeta,
    AssetSavedPayload,
    AssetSelectionContext,
    AssetTransfer,
    CoverBBox,
    SceneAssets,
    TAG_MATCH_MODE,
    get_media_type_from_extension,
    get_media_type_from_file_path,
    migrate_scene_assets_to_library,
    validate_image_data_url,
)
from talemate.agents.visual.schema import (
    AssetAttachmentContext,
    FORMAT_TYPE,
    GEN_TYPE,
    GenerationRequest,
    GenerationResponse,
    Resolution,
    SamplerSettings,
    VIS_TYPE,
)
from talemate.character import Character
from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
    SceneMessage,
    reset_message_id,
)
from talemate.tale_mate import Scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _png_bytes(width: int = 4, height: int = 4, color=(0, 128, 255)) -> bytes:
    """Build a minimal valid PNG in memory."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_data_url(width: int = 4, height: int = 4, color=(0, 128, 255)) -> str:
    return "data:image/png;base64," + base64.b64encode(
        _png_bytes(width, height, color)
    ).decode("utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_message_ids():
    reset_message_id()
    yield
    reset_message_id()


@pytest.fixture
def scene_factory(tmp_path, monkeypatch):
    """Build real Scene objects whose `save_dir` lives under tmp_path.

    We patch `Scene.scenes_dir` (a classmethod) to return tmp_path so the
    SceneAssets `asset_directory` property creates files in the temp dir.
    Each scene uses a distinct `project_name` so multiple scenes can coexist.
    """
    monkeypatch.setattr(
        Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)), raising=True
    )

    created = []

    def _make(project: str = "proj_default") -> Scene:
        scene = Scene()
        scene.project_name = project
        # Ensure save_dir exists (lazy via property too)
        os.makedirs(scene.save_dir, exist_ok=True)
        # Avoid invoking debounced async emit_status during sync tests.
        scene.emit_status = lambda *a, **kw: None
        scene.active = False
        created.append(scene)
        return scene

    yield _make


@pytest.fixture
def scene(scene_factory):
    return scene_factory("proj_main")


# ---------------------------------------------------------------------------
# Module-level helpers — pure functions
# ---------------------------------------------------------------------------


class TestValidateImageDataUrl:
    def test_accepts_well_formed_png(self):
        # No exception.
        validate_image_data_url(_png_data_url())

    @pytest.mark.parametrize("ext", ["jpeg", "webp", "gif"])
    def test_accepts_other_image_types(self, ext):
        validate_image_data_url(f"data:image/{ext};base64,YWJj")

    def test_rejects_non_image_media_type(self):
        with pytest.raises(ValueError, match="Unsupported media type"):
            validate_image_data_url("data:application/pdf;base64,YWJj")

    def test_rejects_empty_payload(self):
        with pytest.raises(ValueError, match="must include base64"):
            validate_image_data_url("data:image/png;base64,")

    def test_rejects_missing_comma(self):
        with pytest.raises(ValueError, match="Invalid image_data format"):
            validate_image_data_url("data:image/png;base64")

    def test_rejects_completely_bogus_string(self):
        with pytest.raises(ValueError, match="Invalid image_data format"):
            validate_image_data_url("not a data url at all")


class TestGetMediaTypeFromExtension:
    @pytest.mark.parametrize(
        "ext, expected",
        [
            (".png", "image/png"),
            ("png", "image/png"),
            ("PNG", "image/png"),
            (".jpg", "image/jpeg"),
            (".jpeg", "image/jpeg"),
            ("JPG", "image/jpeg"),
            (".webp", "image/webp"),
            (".json", "application/json"),
        ],
    )
    def test_normalizes_and_maps(self, ext, expected):
        assert get_media_type_from_extension(ext) == expected

    @pytest.mark.parametrize("ext", [".bmp", ".gif", ".tiff", ""])
    def test_rejects_unsupported(self, ext):
        with pytest.raises(ValueError, match="Unsupported file extension"):
            get_media_type_from_extension(ext)


class TestGetMediaTypeFromFilePath:
    def test_extracts_extension_from_full_path(self):
        assert get_media_type_from_file_path("/var/foo/bar/image.PNG") == "image/png"

    def test_handles_relative_path(self):
        assert get_media_type_from_file_path("a/b/c.jpeg") == "image/jpeg"

    def test_rejects_unsupported_extension(self):
        with pytest.raises(ValueError):
            get_media_type_from_file_path("foo.bmp")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TestCoverBBox:
    def test_defaults_cover_full_image(self):
        bbox = CoverBBox()
        assert bbox.x == 0.0 and bbox.y == 0.0
        assert bbox.w == 1.0 and bbox.h == 1.0

    def test_valid_partial_box(self):
        bbox = CoverBBox(x=0.1, y=0.2, w=0.3, h=0.4)
        assert (bbox.x, bbox.y, bbox.w, bbox.h) == (0.1, 0.2, 0.3, 0.4)

    @pytest.mark.parametrize(
        "kwargs, msg",
        [
            ({"x": 1.0}, "x must be in"),
            ({"x": -0.1}, "x must be in"),
            ({"y": 1.5}, "y must be in"),
            ({"w": 0.0}, "w must be > 0"),
            ({"w": -0.1}, "w must be > 0"),
            ({"h": 0.0}, "h must be > 0"),
            ({"x": 0.6, "w": 0.5}, "x \\+ w must be"),
            ({"y": 0.6, "h": 0.5}, "y \\+ h must be"),
        ],
    )
    def test_rejects_out_of_bounds(self, kwargs, msg):
        with pytest.raises(ValueError, match=msg):
            CoverBBox(**kwargs)


class TestAssetMeta:
    @pytest.mark.parametrize(
        "w, h, expected",
        [
            (100, 100, FORMAT_TYPE.SQUARE),
            (100, 200, FORMAT_TYPE.PORTRAIT),
            (200, 100, FORMAT_TYPE.LANDSCAPE),
        ],
    )
    def test_determine_format(self, w, h, expected):
        assert AssetMeta.determine_format(w, h) == expected

    def test_resolution_from_size(self):
        res = AssetMeta.resolution_from_size(640, 480)
        assert isinstance(res, Resolution)
        assert res.width == 640 and res.height == 480

    def test_set_dimensions_updates_format_and_resolution(self):
        meta = AssetMeta()
        meta.set_dimensions(300, 200)
        assert meta.format == FORMAT_TYPE.LANDSCAPE
        assert meta.resolution == Resolution(width=300, height=200)


class TestAssetSelectionContext:
    def test_defaults(self):
        ctx = AssetSelectionContext()
        assert ctx.mode == "noop"
        assert ctx.has_selection is False
        assert ctx.asset_count == 0
        assert ctx.should_skip() is False

    def test_should_skip_when_noop_with_selection(self):
        ctx = AssetSelectionContext(
            mode="noop", selected=True, selected_asset_ids=["a"]
        )
        assert ctx.should_skip() is True

    def test_should_skip_false_in_prioritize_mode(self):
        ctx = AssetSelectionContext(
            mode="prioritize", selected=True, selected_asset_ids=["a"]
        )
        assert ctx.should_skip() is False

    def test_filter_already_selected_passthrough_in_noop(self):
        ctx = AssetSelectionContext(
            mode="noop", selected=True, selected_asset_ids=["a"]
        )
        assert ctx.filter_already_selected(["a", "b"]) == ["a", "b"]

    def test_filter_already_selected_strips_in_prioritize(self):
        ctx = AssetSelectionContext(
            mode="prioritize", selected=True, selected_asset_ids=["a", "c"]
        )
        assert ctx.filter_already_selected(["a", "b", "c", "d"]) == ["b", "d"]

    def test_update_with_matches_prioritize_concats(self):
        ctx = AssetSelectionContext(mode="prioritize", selected_asset_ids=["a"])
        new_ctx = ctx.update_with_matches(["b", "c"])
        assert new_ctx.mode == "prioritize"
        assert new_ctx.selected_asset_ids == ["a", "b", "c"]
        assert new_ctx.has_selection is True

    def test_update_with_matches_noop_replaces_when_matched(self):
        ctx = AssetSelectionContext(mode="noop", original_asset_ids=["x", "y"])
        new_ctx = ctx.update_with_matches(["b"])
        assert new_ctx.selected is True
        assert new_ctx.selected_asset_ids == ["b"]
        # original_asset_ids preserved
        assert new_ctx.original_asset_ids == ["x", "y"]

    def test_update_with_matches_noop_returns_same_when_no_match(self):
        ctx = AssetSelectionContext(mode="noop", selected_asset_ids=["seed"])
        new_ctx = ctx.update_with_matches([])
        # Returns the same instance (no replacement)
        assert new_ctx is ctx

    def test_get_output_asset_ids_prioritize_concats(self):
        ctx = AssetSelectionContext(mode="prioritize", selected_asset_ids=["a"])
        assert ctx.get_output_asset_ids(["b"]) == ["a", "b"]

    def test_get_output_asset_ids_noop_returns_matched_only(self):
        ctx = AssetSelectionContext(mode="noop", selected_asset_ids=["a"])
        assert ctx.get_output_asset_ids(["b"]) == ["b"]


# ---------------------------------------------------------------------------
# Asset.to_base64
# ---------------------------------------------------------------------------


class TestAssetToBase64:
    def test_reads_file_and_encodes(self, tmp_path):
        asset = Asset(id="abc", file_type="png", media_type="image/png")
        payload = b"\x00\x01ABCDE"
        (tmp_path / "abc.png").write_bytes(payload)
        encoded = asset.to_base64(str(tmp_path))
        assert base64.b64decode(encoded) == payload

    def test_missing_file_raises(self, tmp_path):
        asset = Asset(id="absent", file_type="png", media_type="image/png")
        with pytest.raises(FileNotFoundError):
            asset.to_base64(str(tmp_path))


# ---------------------------------------------------------------------------
# SceneAssets — directory / library plumbing
# ---------------------------------------------------------------------------


class TestSceneAssetsDirectory:
    def test_asset_directory_is_created_lazily(self, scene):
        path = scene.assets.asset_directory
        assert os.path.isdir(path)
        assert path.endswith(os.path.join("proj_main", "assets"))

    def test_asset_directory_raises_when_save_dir_missing(
        self, scene_factory, monkeypatch
    ):
        scene = scene_factory("proj_x")

        # Override save_dir to point at a non-existent directory.
        bogus = os.path.join(scene.save_dir, "..", "absolutely_missing_dir")
        monkeypatch.setattr(
            type(scene),
            "save_dir",
            property(lambda self: bogus),
        )
        with pytest.raises(FileNotFoundError):
            _ = scene.assets.asset_directory


class TestLibraryLoadSave:
    def test_empty_library_returns_empty_dict(self, scene):
        # No library.json exists yet -> empty assets.
        assert scene.assets.assets == {}

    def test_library_path_lives_under_assets_dir(self, scene):
        assert scene.assets._library_path == os.path.join(
            scene.assets.asset_directory, "library.json"
        )

    def test_save_and_reload_round_trip(self, scene):
        meta = AssetMeta(name="hero", tags=["a", "b"])
        asset = Asset(id="id1", file_type="png", media_type="image/png", meta=meta)
        scene.assets.save_asset(asset)

        # File now exists on disk
        with open(scene.assets._library_path) as f:
            data = json.load(f)
        assert "id1" in data["assets"]

        # New SceneAssets backed by the same scene reloads from disk.
        fresh = SceneAssets(scene=scene)
        loaded = fresh.assets
        assert "id1" in loaded
        assert loaded["id1"].meta.name == "hero"
        assert loaded["id1"].meta.tags == ["a", "b"]

    def test_load_library_returns_empty_on_corrupted_json(self, scene):
        Path(scene.assets._library_path).write_text("{ this is not json")
        assert scene.assets._load_library() == {}

    def test_invalidate_cache_forces_reload(self, scene):
        meta = AssetMeta(name="x")
        asset = Asset(id="i", file_type="png", media_type="image/png", meta=meta)
        scene.assets.save_asset(asset)
        # Mutate library.json out from under the cache.
        with open(scene.assets._library_path) as f:
            data = json.load(f)
        data["assets"]["i"]["meta"]["name"] = "renamed"
        with open(scene.assets._library_path, "w") as f:
            json.dump(data, f)

        assert scene.assets.assets["i"].meta.name == "x"  # cached still
        scene.assets._invalidate_cache()
        assert scene.assets.assets["i"].meta.name == "renamed"


class TestAssetsSetter:
    def test_assets_setter_persists_to_library_json(self, scene):
        meta = AssetMeta(name="alpha")
        asset = Asset(id="z", file_type="png", media_type="image/png", meta=meta)
        scene.assets.assets = {"z": asset}
        # On disk
        with open(scene.assets._library_path) as f:
            data = json.load(f)
        assert "z" in data["assets"]
        # In memory cache
        assert scene.assets.assets["z"].id == "z"


class TestValidateAssetIdAndPath:
    def test_validate_asset_id_true_for_known(self, scene):
        scene.assets.save_asset(
            Asset(id="kept", file_type="png", media_type="image/png")
        )
        assert scene.assets.validate_asset_id("kept") is True

    def test_validate_asset_id_false_for_unknown(self, scene):
        assert scene.assets.validate_asset_id("missing") is False

    def test_asset_path_returns_full_path(self, scene):
        scene.assets.save_asset(
            Asset(id="abcd", file_type="webp", media_type="image/webp")
        )
        path = scene.assets.asset_path("abcd")
        assert path.endswith("abcd.webp")
        assert path.startswith(scene.assets.asset_directory)

    def test_asset_path_returns_none_when_unknown(self, scene):
        assert scene.assets.asset_path("nope") is None


class TestSceneAssetsDictAndSceneInfo:
    def test_dict_includes_cover_image_and_assets(self, scene):
        scene.assets.cover_image = "cover-id"
        scene.assets.save_asset(Asset(id="a1", file_type="png", media_type="image/png"))
        result = scene.assets.dict()
        assert result["cover_image"] == "cover-id"
        assert "a1" in result["assets"]

    def test_scene_info_returns_cover_image_and_backdrop(self, scene):
        scene.assets.cover_image = "cv"
        info = scene.assets.scene_info()
        assert info == {
            "cover_image": "cv",
            "backdrop": None,
            "backdrop_enabled": True,
        }

    def test_load_assets_is_a_noop(self, scene):
        # Legacy method -- must not raise and must not modify state.
        scene.assets.load_assets({"foo": {"id": "foo"}})
        assert scene.assets.assets == {}


# ---------------------------------------------------------------------------
# add_asset / dedupe / signal
# ---------------------------------------------------------------------------


class TestAddAsset:
    async def test_creates_file_and_record(self, scene):
        payload = b"hello-png-bytes"
        expected_id = hashlib.sha256(payload).hexdigest()

        asset = await scene.assets.add_asset(payload, "png", "image/png")
        assert asset.id == expected_id
        assert asset.file_type == "png"
        assert asset.media_type == "image/png"

        # File was written
        on_disk = os.path.join(scene.assets.asset_directory, f"{expected_id}.png")
        assert os.path.isfile(on_disk)
        with open(on_disk, "rb") as f:
            assert f.read() == payload

        # And recorded in library.json
        assert expected_id in scene.assets.assets

    async def test_dedupes_identical_bytes(self, scene):
        payload = b"identical"
        a = await scene.assets.add_asset(payload, "png", "image/png")
        b = await scene.assets.add_asset(payload, "png", "image/png")
        assert a.id == b.id
        # Only one library entry
        assert list(scene.assets.assets.keys()) == [a.id]

    async def test_uses_provided_meta(self, scene):
        meta = AssetMeta(name="custom", tags=["t1"])
        asset = await scene.assets.add_asset(b"bytes-x", "png", "image/png", meta=meta)
        assert asset.meta.name == "custom"
        assert asset.meta.tags == ["t1"]


class TestBytesFromImageData:
    def test_decodes_data_url(self, scene):
        url = _png_data_url()
        decoded = scene.assets.bytes_from_image_data(url)
        # Decoded == raw PNG bytes
        assert decoded.startswith(b"\x89PNG\r\n\x1a\n")

    def test_invalid_url_raises(self, scene):
        with pytest.raises(ValueError):
            scene.assets.bytes_from_image_data("not a data url")


class TestAddAssetFromImageData:
    async def test_adds_with_dimensions_set_on_meta(self, scene):
        url = _png_data_url(width=10, height=20)
        asset = await scene.assets.add_asset_from_image_data(url)
        assert asset.media_type == "image/png"
        assert asset.file_type == "png"
        # Image is portrait (10x20)
        assert asset.meta.format == FORMAT_TYPE.PORTRAIT
        assert asset.meta.resolution == Resolution(width=10, height=20)


class TestAddAssetFromFilePath:
    async def test_reads_file_and_creates_asset(self, scene, tmp_path):
        # NOTE: add_asset_from_file_path passes the raw extension (with leading
        # dot) into add_asset, which then joins it with another '.', producing
        # filenames like "<id>..png" on disk. Test pins this current behavior.
        png = tmp_path / "src.png"
        png_payload = _png_bytes(8, 8)
        png.write_bytes(png_payload)
        asset = await scene.assets.add_asset_from_file_path(str(png))
        assert asset.media_type == "image/png"
        assert asset.file_type == ".png"
        on_disk = os.path.join(
            scene.assets.asset_directory, f"{asset.id}.{asset.file_type}"
        )
        assert os.path.isfile(on_disk)
        with open(on_disk, "rb") as f:
            assert f.read() == png_payload


class TestAddAssetFromGenerationResponse:
    async def test_extracts_meta_and_dimensions(self, scene):
        req = GenerationRequest(
            prompt="a cat",
            negative_prompt="blurry",
            vis_type=VIS_TYPE.CHARACTER_PORTRAIT,
            gen_type=GEN_TYPE.TEXT_TO_IMAGE,
            character_name="Alice",
            format=FORMAT_TYPE.SQUARE,
            resolution=Resolution(width=8, height=8),
            sampler_settings=SamplerSettings(steps=10),
            asset_attachment_context=AssetAttachmentContext(
                asset_name="hero-shot", tags=["primary"]
            ),
        )
        resp = GenerationResponse(generated=_png_bytes(8, 8), request=req)
        asset = await scene.assets.add_asset_from_generation_response(resp)
        assert asset.meta.character_name == "Alice"
        assert asset.meta.prompt == "a cat"
        assert asset.meta.negative_prompt == "blurry"
        assert asset.meta.vis_type == VIS_TYPE.CHARACTER_PORTRAIT
        assert asset.meta.name == "hero-shot"
        assert asset.meta.tags == ["primary"]
        # set_dimensions overwrote the format based on actual image (8x8 -> SQUARE)
        assert asset.meta.format == FORMAT_TYPE.SQUARE
        assert asset.meta.resolution == Resolution(width=8, height=8)

    async def test_rejects_response_without_image_data(self, scene):
        resp = GenerationResponse(generated=None, request=GenerationRequest())
        with pytest.raises(ValueError, match="does not contain generated"):
            await scene.assets.add_asset_from_generation_response(resp)

    async def test_rejects_response_without_request(self, scene):
        resp = GenerationResponse(generated=_png_bytes(), request=None)
        with pytest.raises(
            ValueError, match="does not have a reference to the request"
        ):
            await scene.assets.add_asset_from_generation_response(resp)


# ---------------------------------------------------------------------------
# update_asset_meta / get_asset / get_asset_bytes_*
# ---------------------------------------------------------------------------


class TestGetAndUpdateAsset:
    def test_get_asset_returns_pydantic_object(self, scene):
        scene.assets.save_asset(Asset(id="x", file_type="png", media_type="image/png"))
        assert scene.assets.get_asset("x").id == "x"

    def test_update_asset_meta_persists(self, scene):
        scene.assets.save_asset(Asset(id="x", file_type="png", media_type="image/png"))
        scene.assets.update_asset_meta("x", AssetMeta(name="new"))
        # in-memory cache reflects it
        assert scene.assets.get_asset("x").meta.name == "new"
        # And the on-disk library too
        with open(scene.assets._library_path) as f:
            data = json.load(f)
        assert data["assets"]["x"]["meta"]["name"] == "new"

    def test_update_asset_meta_raises_for_unknown(self, scene):
        with pytest.raises(KeyError):
            scene.assets.update_asset_meta("nope", AssetMeta())


class TestGetAssetBytes:
    async def test_returns_raw_bytes(self, scene):
        a = await scene.assets.add_asset(b"my-bytes", "png", "image/png")
        assert scene.assets.get_asset_bytes(a.id) == b"my-bytes"

    def test_returns_none_for_unknown_id(self, scene):
        assert scene.assets.get_asset_bytes("absent") is None

    async def test_get_asset_bytes_many_skips_missing(self, scene):
        a = await scene.assets.add_asset(b"aa", "png", "image/png")
        b = await scene.assets.add_asset(b"bb", "png", "image/png")
        results = scene.assets.get_asset_bytes_many([a.id, "absent", b.id])
        assert results == [b"aa", b"bb"]

    async def test_get_asset_bytes_as_base64(self, scene):
        a = await scene.assets.add_asset(b"hi", "png", "image/png")
        assert (
            scene.assets.get_asset_bytes_as_base64(a.id)
            == base64.b64encode(b"hi").decode()
        )

    def test_get_asset_bytes_as_base64_returns_none(self, scene):
        assert scene.assets.get_asset_bytes_as_base64("missing") is None

    async def test_get_asset_bytes_as_base64_many_skips_missing(self, scene):
        a = await scene.assets.add_asset(b"aa", "png", "image/png")
        out = scene.assets.get_asset_bytes_as_base64_many([a.id, "absent"])
        assert out == [base64.b64encode(b"aa").decode()]


# ---------------------------------------------------------------------------
# search_assets / select_assets
# ---------------------------------------------------------------------------


@pytest.fixture
def populated_scene(scene):
    """Scene with three assets exercising all the search filters."""
    scene.assets.save_asset(
        Asset(
            id="alice_portrait",
            file_type="png",
            media_type="image/png",
            meta=AssetMeta(
                vis_type=VIS_TYPE.CHARACTER_PORTRAIT,
                character_name="Alice",
                tags=["red", "Hero"],
                reference=[VIS_TYPE.CHARACTER_PORTRAIT],
            ),
        )
    )
    scene.assets.save_asset(
        Asset(
            id="bob_card",
            file_type="png",
            media_type="image/png",
            meta=AssetMeta(
                vis_type=VIS_TYPE.CHARACTER_CARD,
                character_name="Bob",
                tags=["blue"],
                reference=[VIS_TYPE.SCENE_CARD],
            ),
        )
    )
    scene.assets.save_asset(
        Asset(
            id="scene_bg",
            file_type="png",
            media_type="image/png",
            meta=AssetMeta(
                vis_type=VIS_TYPE.SCENE_BACKGROUND,
                tags=[],
                reference=[],
            ),
        )
    )
    return scene


class TestSearchAssets:
    def test_no_filters_returns_all(self, populated_scene):
        ids = populated_scene.assets.search_assets()
        assert sorted(ids) == ["alice_portrait", "bob_card", "scene_bg"]

    def test_filter_by_single_vis_type(self, populated_scene):
        ids = populated_scene.assets.search_assets(vis_type=VIS_TYPE.CHARACTER_PORTRAIT)
        assert ids == ["alice_portrait"]

    def test_filter_by_vis_type_list(self, populated_scene):
        ids = populated_scene.assets.search_assets(
            vis_type=[VIS_TYPE.CHARACTER_PORTRAIT, VIS_TYPE.CHARACTER_CARD]
        )
        assert sorted(ids) == ["alice_portrait", "bob_card"]

    def test_filter_by_character_name_case_insensitive(self, populated_scene):
        ids = populated_scene.assets.search_assets(character_name="alice")
        assert ids == ["alice_portrait"]

    def test_filter_by_partial_character_name(self, populated_scene):
        # substring match
        ids = populated_scene.assets.search_assets(character_name="li")
        assert ids == ["alice_portrait"]

    def test_tag_match_all(self, populated_scene):
        ids = populated_scene.assets.search_assets(
            tags=["red", "hero"], tag_match_mode=TAG_MATCH_MODE.ALL
        )
        assert ids == ["alice_portrait"]

    def test_tag_match_all_strict(self, populated_scene):
        # Asset alice has only red+hero; requesting red+blue must miss.
        ids = populated_scene.assets.search_assets(
            tags=["red", "blue"], tag_match_mode=TAG_MATCH_MODE.ALL
        )
        assert ids == []

    def test_tag_match_any(self, populated_scene):
        ids = populated_scene.assets.search_assets(
            tags=["red", "blue"], tag_match_mode=TAG_MATCH_MODE.ANY
        )
        assert sorted(ids) == ["alice_portrait", "bob_card"]

    def test_tag_match_none(self, populated_scene):
        # NONE means: asset must have no overlap with the supplied tags.
        ids = populated_scene.assets.search_assets(
            tags=["red"], tag_match_mode=TAG_MATCH_MODE.NONE
        )
        assert sorted(ids) == ["bob_card", "scene_bg"]

    def test_invalid_tag_match_mode_raises(self, populated_scene):
        with pytest.raises(ValueError, match="Invalid tag_match_mode"):
            populated_scene.assets.search_assets(tags=["red"], tag_match_mode="bogus")

    def test_reference_vis_types_filter(self, populated_scene):
        ids = populated_scene.assets.search_assets(
            reference_vis_types=[VIS_TYPE.SCENE_CARD]
        )
        assert ids == ["bob_card"]

    def test_combined_filters(self, populated_scene):
        ids = populated_scene.assets.search_assets(
            vis_type=VIS_TYPE.CHARACTER_PORTRAIT, tags=["hero"]
        )
        assert ids == ["alice_portrait"]


class TestSelectAssets:
    def test_filters_by_vis_types(self, populated_scene):
        all_ids = list(populated_scene.assets.assets.keys())
        ids = populated_scene.assets.select_assets(
            all_ids, vis_types=[VIS_TYPE.CHARACTER_PORTRAIT]
        )
        assert ids == ["alice_portrait"]

    def test_filters_by_reference_vis_types(self, populated_scene):
        all_ids = list(populated_scene.assets.assets.keys())
        ids = populated_scene.assets.select_assets(
            all_ids, reference_vis_types=[VIS_TYPE.SCENE_CARD]
        )
        assert ids == ["bob_card"]

    def test_skips_missing_ids(self, populated_scene):
        ids = populated_scene.assets.select_assets(
            ["alice_portrait", "nonexistent"],
            vis_types=[VIS_TYPE.CHARACTER_PORTRAIT],
        )
        assert ids == ["alice_portrait"]

    def test_no_filters_returns_all_supplied(self, populated_scene):
        ids = populated_scene.assets.select_assets(["alice_portrait", "bob_card"])
        assert sorted(ids) == ["alice_portrait", "bob_card"]


# ---------------------------------------------------------------------------
# Cover-image / avatar setters
# ---------------------------------------------------------------------------


class TestSceneCoverImage:
    async def test_set_cover_image_with_valid_id(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        result = await scene.assets.set_scene_cover_image(a.id)
        assert result == a.id
        assert scene.assets.cover_image == a.id

    async def test_set_cover_image_invalid_returns_none(self, scene):
        result = await scene.assets.set_scene_cover_image("nope")
        assert result is None
        assert scene.assets.cover_image is None

    async def test_set_cover_image_no_override_keeps_existing(self, scene):
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        b = await scene.assets.add_asset(b"b", "png", "image/png")
        await scene.assets.set_scene_cover_image(a.id)
        # Non-override returns the existing value, doesn't update
        result = await scene.assets.set_scene_cover_image(b.id, override=False)
        assert result == a.id
        assert scene.assets.cover_image == a.id

    async def test_set_cover_image_override_replaces(self, scene):
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        b = await scene.assets.add_asset(b"b", "png", "image/png")
        await scene.assets.set_scene_cover_image(a.id)
        result = await scene.assets.set_scene_cover_image(b.id, override=True)
        assert result == b.id
        assert scene.assets.cover_image == b.id


class TestSceneBackdrop:
    async def test_set_backdrop_with_valid_id(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        result = await scene.assets.set_scene_backdrop(asset_id=a.id)
        assert result == a.id
        assert scene.assets.backdrop == a.id
        # enabled defaults to True and is untouched by asset-only updates
        assert scene.assets.backdrop_enabled is True

    async def test_set_backdrop_invalid_returns_none(self, scene):
        result = await scene.assets.set_scene_backdrop(asset_id="nope")
        assert result is None
        assert scene.assets.backdrop is None

    async def test_toggle_enabled_keeps_asset(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        await scene.assets.set_scene_backdrop(asset_id=a.id)
        result = await scene.assets.set_scene_backdrop(enabled=False)
        assert result == a.id
        assert scene.assets.backdrop == a.id
        assert scene.assets.backdrop_enabled is False

    async def test_set_asset_does_not_reenable(self, scene):
        # a new backdrop image must not override an explicit "off"
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        b = await scene.assets.add_asset(b"b", "png", "image/png")
        await scene.assets.set_scene_backdrop(asset_id=a.id, enabled=False)
        await scene.assets.set_scene_backdrop(asset_id=b.id)
        assert scene.assets.backdrop == b.id
        assert scene.assets.backdrop_enabled is False

    async def test_clear_removes_asset(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        await scene.assets.set_scene_backdrop(asset_id=a.id)
        result = await scene.assets.set_scene_backdrop(clear=True)
        assert result is None
        assert scene.assets.backdrop is None
        assert scene.assets.backdrop_enabled is True

    async def test_clear_ignores_asset_id(self, scene):
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        b = await scene.assets.add_asset(b"b", "png", "image/png")
        await scene.assets.set_scene_backdrop(asset_id=a.id)
        await scene.assets.set_scene_backdrop(asset_id=b.id, clear=True)
        assert scene.assets.backdrop is None

    async def test_backdrop_in_dict_and_scene_info(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        await scene.assets.set_scene_backdrop(asset_id=a.id, enabled=True)
        for data in (scene.assets.dict(), scene.assets.scene_info()):
            assert data["backdrop"] == a.id
            assert data["backdrop_enabled"] is True


class TestSceneCoverImageFromSources:
    async def test_from_bytes(self, scene):
        rid = await scene.assets.set_scene_cover_image_from_bytes(_png_bytes())
        assert scene.assets.cover_image == rid
        assert rid in scene.assets.assets

    async def test_from_image_data(self, scene):
        rid = await scene.assets.set_scene_cover_image_from_image_data(_png_data_url())
        assert scene.assets.cover_image == rid

    async def test_from_file_path(self, scene, tmp_path):
        png = tmp_path / "input.png"
        png.write_bytes(_png_bytes())
        rid = await scene.assets.set_scene_cover_image_from_file_path(str(png))
        assert scene.assets.cover_image == rid


class TestCharacterCoverImage:
    async def test_set_character_cover_image_valid(self, scene):
        char = Character(name="Alice")
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        result = await scene.assets.set_character_cover_image(char, a.id)
        assert result == a.id
        assert char.cover_image == a.id

    async def test_set_character_cover_image_invalid(self, scene):
        char = Character(name="Alice")
        result = await scene.assets.set_character_cover_image(char, "nope")
        assert result is None
        assert char.cover_image is None

    async def test_no_override_preserves_existing_cover(self, scene):
        char = Character(name="Alice")
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        b = await scene.assets.add_asset(b"b", "png", "image/png")
        await scene.assets.set_character_cover_image(char, a.id)
        result = await scene.assets.set_character_cover_image(char, b.id)
        assert result == a.id
        assert char.cover_image == a.id

    async def test_override_replaces(self, scene):
        char = Character(name="Alice")
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        b = await scene.assets.add_asset(b"b", "png", "image/png")
        await scene.assets.set_character_cover_image(char, a.id)
        result = await scene.assets.set_character_cover_image(char, b.id, override=True)
        assert result == b.id
        assert char.cover_image == b.id

    async def test_from_bytes_helper(self, scene):
        char = Character(name="Alice")
        rid = await scene.assets.set_character_cover_image_from_bytes(
            char, _png_bytes()
        )
        assert char.cover_image == rid

    async def test_from_image_data_helper(self, scene):
        char = Character(name="Alice")
        rid = await scene.assets.set_character_cover_image_from_image_data(
            char, _png_data_url()
        )
        assert char.cover_image == rid

    async def test_from_file_path_helper(self, scene, tmp_path):
        png = tmp_path / "in.png"
        png.write_bytes(_png_bytes())
        char = Character(name="Alice")
        rid = await scene.assets.set_character_cover_image_from_file_path(
            char, str(png)
        )
        assert char.cover_image == rid


class TestCharacterAvatars:
    async def test_set_character_avatar_valid(self, scene):
        char = Character(name="Alice")
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        result = await scene.assets.set_character_avatar(char, a.id)
        assert result == a.id
        assert char.avatar == a.id

    async def test_set_character_avatar_invalid(self, scene):
        char = Character(name="Alice")
        result = await scene.assets.set_character_avatar(char, "nope")
        assert result is None
        assert char.avatar is None

    async def test_set_character_avatar_no_override(self, scene):
        char = Character(name="Alice")
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        b = await scene.assets.add_asset(b"b", "png", "image/png")
        await scene.assets.set_character_avatar(char, a.id)
        result = await scene.assets.set_character_avatar(char, b.id)
        assert result == a.id
        assert char.avatar == a.id

    async def test_set_character_avatar_override(self, scene):
        char = Character(name="Alice")
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        b = await scene.assets.add_asset(b"b", "png", "image/png")
        await scene.assets.set_character_avatar(char, a.id)
        result = await scene.assets.set_character_avatar(char, b.id, override=True)
        assert result == b.id
        assert char.avatar == b.id

    async def test_set_character_current_avatar_valid(self, scene):
        char = Character(name="Alice")
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        result = await scene.assets.set_character_current_avatar(char, a.id)
        assert result == a.id
        assert char.current_avatar == a.id

    async def test_set_character_current_avatar_invalid(self, scene):
        char = Character(name="Alice")
        result = await scene.assets.set_character_current_avatar(char, "nope")
        assert result is None
        assert char.current_avatar is None

    async def test_set_character_current_avatar_no_override(self, scene):
        char = Character(name="Alice")
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        b = await scene.assets.add_asset(b"b", "png", "image/png")
        await scene.assets.set_character_current_avatar(char, a.id)
        result = await scene.assets.set_character_current_avatar(char, b.id)
        assert result == a.id

    async def test_set_character_current_avatar_override(self, scene):
        char = Character(name="Alice")
        a = await scene.assets.add_asset(b"a", "png", "image/png")
        b = await scene.assets.add_asset(b"b", "png", "image/png")
        await scene.assets.set_character_current_avatar(char, a.id)
        result = await scene.assets.set_character_current_avatar(
            char, b.id, override=True
        )
        assert result == b.id


# ---------------------------------------------------------------------------
# remove_asset and cleanup methods
# ---------------------------------------------------------------------------


class TestRemoveAsset:
    async def test_removes_record_and_file(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        path = scene.assets.asset_path(a.id)
        assert os.path.exists(path)

        scene.assets.remove_asset(a.id)
        assert a.id not in scene.assets.assets
        assert not os.path.exists(path)

    async def test_remove_asset_when_file_missing(self, scene):
        # Add and then delete the file out-of-band; remove_asset should
        # still complete (FileNotFoundError swallowed).
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        os.remove(scene.assets.asset_path(a.id))
        scene.assets.remove_asset(a.id)
        assert a.id not in scene.assets.assets

    async def test_remove_asset_clears_dangling_scene_cover(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        await scene.assets.set_scene_cover_image(a.id)
        scene.assets.remove_asset(a.id)
        assert scene.assets.cover_image is None


class TestCleanupCoverImages:
    def test_cleans_dangling_scene_cover(self, scene):
        # Asset reference that no longer exists.
        scene.assets.cover_image = "ghost"
        cleaned = scene.assets.cleanup_cover_images()
        assert cleaned is True
        assert scene.assets.cover_image is None

    async def test_keeps_valid_scene_cover(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        scene.assets.cover_image = a.id
        cleaned = scene.assets.cleanup_cover_images()
        assert cleaned is False
        assert scene.assets.cover_image == a.id

    def test_cleans_dangling_character_cover(self, scene):
        char = Character(name="Alice", cover_image="ghost")
        scene.character_data["Alice"] = char
        cleaned = scene.assets.cleanup_cover_images()
        assert cleaned is True
        assert char.cover_image is None

    def test_cleans_dangling_backdrop(self, scene):
        scene.assets.backdrop = "ghost"
        cleaned = scene.assets.cleanup_cover_images()
        assert cleaned is True
        assert scene.assets.backdrop is None

    async def test_keeps_valid_backdrop(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        scene.assets.backdrop = a.id
        cleaned = scene.assets.cleanup_cover_images()
        assert cleaned is False
        assert scene.assets.backdrop == a.id


class TestCleanupCharacterAvatars:
    def test_cleans_dangling_default_and_current_avatar(self, scene):
        char = Character(name="Alice", avatar="ghost1", current_avatar="ghost2")
        scene.character_data["Alice"] = char
        cleaned = scene.assets.cleanup_character_avatars()
        assert cleaned is True
        assert char.avatar is None
        assert char.current_avatar is None

    async def test_keeps_valid_avatars(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        char = Character(name="Alice", avatar=a.id, current_avatar=a.id)
        scene.character_data["Alice"] = char
        cleaned = scene.assets.cleanup_character_avatars()
        assert cleaned is False
        assert char.avatar == a.id
        assert char.current_avatar == a.id


class TestCleanupMessageAvatars:
    def test_cleans_dangling_message_avatar(self, scene):
        msg = CharacterMessage(
            message="Alice: hi", asset_id="ghost", asset_type="avatar"
        )
        scene.history = [msg]
        cleaned = scene.assets.cleanup_message_avatars()
        assert cleaned is True
        assert msg.asset_id is None
        assert msg.asset_type is None

    async def test_preserves_valid_message_avatar(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        msg = CharacterMessage(message="Alice: hi", asset_id=a.id, asset_type="avatar")
        scene.history = [msg]
        cleaned = scene.assets.cleanup_message_avatars()
        assert cleaned is False
        assert msg.asset_id == a.id

    def test_ignores_messages_without_asset_id(self, scene):
        msg = SceneMessage(message="generic")
        scene.history = [msg]
        # Should not raise even though SceneMessage has no asset_id attribute.
        assert scene.assets.cleanup_message_avatars() is False


# ---------------------------------------------------------------------------
# update_message_asset / clear_message_asset / smart_attach_asset
# ---------------------------------------------------------------------------


class TestUpdateMessageAsset:
    async def test_updates_character_message(self, scene):
        a = await scene.assets.add_asset(
            b"x",
            "png",
            "image/png",
            meta=AssetMeta(vis_type=VIS_TYPE.CHARACTER_PORTRAIT),
        )
        msg = CharacterMessage(message="Alice: hi")
        scene.history = [msg]
        result = await scene.assets.update_message_asset(msg.id, a.id)
        assert result is msg
        assert msg.asset_id == a.id
        assert msg.asset_type == "avatar"

    async def test_updates_scene_illustration_for_narrator(self, scene):
        a = await scene.assets.add_asset(
            b"y",
            "png",
            "image/png",
            meta=AssetMeta(vis_type=VIS_TYPE.SCENE_ILLUSTRATION),
        )
        msg = NarratorMessage(message="The scene")
        scene.history = [msg]
        await scene.assets.update_message_asset(msg.id, a.id)
        assert msg.asset_type == "scene_illustration"

    async def test_unknown_message_returns_none(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        result = await scene.assets.update_message_asset(99999, a.id)
        assert result is None

    async def test_unsupported_message_type_raises(self, scene):
        a = await scene.assets.add_asset(b"x", "png", "image/png")
        msg = SceneMessage(message="generic")
        scene.history = [msg]
        with pytest.raises(ValueError, match="does not support assets"):
            await scene.assets.update_message_asset(msg.id, a.id)

    async def test_invalid_asset_id_raises(self, scene):
        msg = CharacterMessage(message="Alice: hi")
        scene.history = [msg]
        with pytest.raises(ValueError, match="Invalid asset_id"):
            await scene.assets.update_message_asset(msg.id, "ghost")

    async def test_unspecified_vis_type_raises(self, scene):
        a = await scene.assets.add_asset(
            b"x", "png", "image/png", meta=AssetMeta(vis_type=VIS_TYPE.UNSPECIFIED)
        )
        msg = CharacterMessage(message="Alice: hi")
        scene.history = [msg]
        with pytest.raises(ValueError, match="Asset type not valid"):
            await scene.assets.update_message_asset(msg.id, a.id)


class TestClearMessageAsset:
    async def test_clears_asset_fields(self, scene):
        msg = CharacterMessage(
            message="Alice: hi", asset_id="some-id", asset_type="avatar"
        )
        scene.history = [msg]
        result = await scene.assets.clear_message_asset(msg.id)
        assert result is msg
        assert msg.asset_id is None
        assert msg.asset_type is None

    async def test_clear_unknown_message(self, scene):
        result = await scene.assets.clear_message_asset(999)
        assert result is None

    async def test_clear_unsupported_message_type(self, scene):
        msg = SceneMessage(message="bare")
        scene.history = [msg]
        result = await scene.assets.clear_message_asset(msg.id)
        assert result is None


class TestSmartAttachAsset:
    async def test_attaches_to_last_compatible_message(self, scene):
        # Two messages, the most recent is character, which is supported.
        narr = NarratorMessage(message="Earlier narration")
        char = CharacterMessage(message="Alice: greetings")
        scene.history = [narr, char]

        a = await scene.assets.add_asset(
            b"x",
            "png",
            "image/png",
            meta=AssetMeta(vis_type=VIS_TYPE.SCENE_ILLUSTRATION),
        )
        result = await scene.assets.smart_attach_asset(a.id)
        assert result == [char]
        assert char.asset_id == a.id
        assert char.asset_type == "scene_illustration"

    async def test_returns_none_when_history_empty(self, scene):
        scene.history = []
        a = await scene.assets.add_asset(
            b"x",
            "png",
            "image/png",
            meta=AssetMeta(vis_type=VIS_TYPE.SCENE_ILLUSTRATION),
        )
        assert await scene.assets.smart_attach_asset(a.id) is None

    async def test_no_override_keeps_existing(self, scene):
        char = CharacterMessage(
            message="Alice: hi", asset_id="prior", asset_type="avatar"
        )
        scene.history = [char]
        a = await scene.assets.add_asset(
            b"x",
            "png",
            "image/png",
            meta=AssetMeta(vis_type=VIS_TYPE.SCENE_ILLUSTRATION),
        )
        await scene.assets.smart_attach_asset(a.id, allow_override=False)
        # Existing asset_id preserved (continue branch hit)
        assert char.asset_id == "prior"

    async def test_attaches_to_explicit_message_ids(self, scene):
        m1 = NarratorMessage(message="one")
        m2 = NarratorMessage(message="two")
        scene.history = [m1, m2]
        a = await scene.assets.add_asset(
            b"x",
            "png",
            "image/png",
            meta=AssetMeta(vis_type=VIS_TYPE.SCENE_ILLUSTRATION),
        )
        result = await scene.assets.smart_attach_asset(a.id, message_ids=[m1.id, m2.id])
        assert {m.id for m in result} == {m1.id, m2.id}
        assert m1.asset_id == a.id and m2.asset_id == a.id


# ---------------------------------------------------------------------------
# transfer_asset
# ---------------------------------------------------------------------------


class TestTransferAsset:
    async def test_round_trip_copies_bytes_and_meta(self, scene_factory, tmp_path):
        # Source scene gets a real asset on disk
        src = scene_factory("src_proj")
        src.filename = "src.json"
        src.name = "Source"
        src_meta = AssetMeta(name="art", tags=["t1"])
        src_asset = await src.assets.add_asset(
            b"copyme", "png", "image/png", meta=src_meta
        )

        # A scene file on disk pointing at the source's project_name.
        src_scene_path = os.path.join(src.save_dir, "src.json")
        with open(src_scene_path, "w") as f:
            json.dump({"name": "Source"}, f)

        dst = scene_factory("dst_proj")

        result = await dst.assets.transfer_asset(
            AssetTransfer(source_scene_path=src_scene_path, asset_id=src_asset.id)
        )
        assert result is True

        # Destination has the same asset id (content hashing -> same hash)
        assert src_asset.id in dst.assets.assets
        # The bytes are the same on disk
        assert dst.assets.get_asset_bytes(src_asset.id) == b"copyme"
        # Meta carried over (name)
        assert dst.assets.get_asset(src_asset.id).meta.name == "art"

    async def test_transfer_missing_asset_returns_false(self, scene_factory, tmp_path):
        src = scene_factory("src2")
        src.filename = "src.json"
        src_scene_path = os.path.join(src.save_dir, "src.json")
        with open(src_scene_path, "w") as f:
            json.dump({"name": "Source"}, f)

        dst = scene_factory("dst2")
        result = await dst.assets.transfer_asset(
            AssetTransfer(source_scene_path=src_scene_path, asset_id="not-there")
        )
        assert result is False

    async def test_transfer_when_source_scene_path_missing(self, scene_factory):
        dst = scene_factory("dst3")
        result = await dst.assets.transfer_asset(
            AssetTransfer(source_scene_path="/no/such/file.json", asset_id="x")
        )
        assert result is False


# ---------------------------------------------------------------------------
# AssetSavedPayload (smoke for pydantic instantiation)
# ---------------------------------------------------------------------------


class TestAssetSavedPayload:
    def test_default_attachment_context(self):
        a = Asset(id="i", file_type="png", media_type="image/png")
        payload = AssetSavedPayload(asset=a, new_asset=True)
        assert payload.asset_attachment_context == AssetAttachmentContext()

    def test_attachment_context_passthrough(self):
        a = Asset(id="i", file_type="png", media_type="image/png")
        ctx = AssetAttachmentContext(scene_cover=True, asset_name="X")
        payload = AssetSavedPayload(
            asset=a, new_asset=False, asset_attachment_context=ctx
        )
        assert payload.asset_attachment_context.asset_name == "X"
        assert payload.asset_attachment_context.scene_cover is True


# ---------------------------------------------------------------------------
# migrate_scene_assets_to_library
# ---------------------------------------------------------------------------


class TestMigrateSceneAssetsToLibrary:
    def _write_scene(self, project_dir: Path, name: str, assets: dict):
        scene_data = {"name": name, "assets": {"assets": assets}}
        path = project_dir / f"{name}.json"
        path.write_text(json.dumps(scene_data))
        return path

    def _asset_dict(self, asset_id: str, name: str | None = None) -> dict:
        return {
            "id": asset_id,
            "file_type": "png",
            "media_type": "image/png",
            "meta": {"name": name} if name else {},
        }

    def test_creates_library_for_project_with_assets(self, tmp_path):
        proj = tmp_path / "proj_a"
        proj.mkdir()
        self._write_scene(
            proj, "scene_a", {"id1": self._asset_dict("id1", name="hello")}
        )

        migrate_scene_assets_to_library(root=tmp_path)

        lib_path = proj / "assets" / "library.json"
        assert lib_path.exists()
        data = json.loads(lib_path.read_text())
        assert "id1" in data["assets"]
        assert data["assets"]["id1"]["meta"]["name"] == "hello"

    def test_skips_project_without_scene_files(self, tmp_path):
        proj = tmp_path / "proj_b"
        proj.mkdir()
        # Has only non-JSON files
        (proj / "readme.txt").write_text("nothing")

        migrate_scene_assets_to_library(root=tmp_path)
        assert not (proj / "assets" / "library.json").exists()

    def test_idempotent_does_not_overwrite_existing_library(self, tmp_path):
        proj = tmp_path / "proj_c"
        proj.mkdir()
        # Pre-existing library.json must not be clobbered.
        (proj / "assets").mkdir()
        existing = {"assets": {"manual": self._asset_dict("manual", "kept")}}
        (proj / "assets" / "library.json").write_text(json.dumps(existing))

        # Scene also has its own assets, but migration should skip overwriting.
        self._write_scene(
            proj, "scene_c", {"new": self._asset_dict("new", "discarded")}
        )

        migrate_scene_assets_to_library(root=tmp_path)
        data = json.loads((proj / "assets" / "library.json").read_text())
        assert "manual" in data["assets"]
        assert "new" not in data["assets"]

    def test_merges_assets_across_multiple_scenes(self, tmp_path):
        proj = tmp_path / "proj_d"
        proj.mkdir()
        self._write_scene(proj, "scene1", {"a": self._asset_dict("a", "alpha")})
        self._write_scene(proj, "scene2", {"b": self._asset_dict("b", "beta")})

        migrate_scene_assets_to_library(root=tmp_path)
        data = json.loads((proj / "assets" / "library.json").read_text())
        assert sorted(data["assets"].keys()) == ["a", "b"]

    def test_handles_scene_files_with_bad_json(self, tmp_path):
        proj = tmp_path / "proj_e"
        proj.mkdir()
        # One bad and one good scene - migration should still emit a library
        # for the good one.
        (proj / "broken.json").write_text("{ not valid json")
        self._write_scene(proj, "good", {"a": self._asset_dict("a", "alpha")})

        migrate_scene_assets_to_library(root=tmp_path)
        data = json.loads((proj / "assets" / "library.json").read_text())
        assert "a" in data["assets"]

    def test_skips_when_no_assets_in_any_scene(self, tmp_path):
        proj = tmp_path / "proj_f"
        proj.mkdir()
        self._write_scene(proj, "empty", {})
        migrate_scene_assets_to_library(root=tmp_path)
        # No library created when no assets to write
        assert not (proj / "assets" / "library.json").exists()

    def test_missing_root_does_not_raise(self, tmp_path):
        # Path that doesn't exist -> early return, no raise.
        migrate_scene_assets_to_library(root=tmp_path / "does_not_exist")

    def test_uses_default_scenes_dir_when_root_none(self, tmp_path, monkeypatch):
        # Patch SCENES_DIR to ensure we don't touch the real one.
        monkeypatch.setattr(scene_assets, "SCENES_DIR", tmp_path)
        proj = tmp_path / "proj_g"
        proj.mkdir()
        self._write_scene(proj, "scene", {"id": self._asset_dict("id", "x")})
        migrate_scene_assets_to_library(root=None)
        assert (proj / "assets" / "library.json").exists()
