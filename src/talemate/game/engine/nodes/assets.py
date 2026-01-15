"""
Nodes for managing scene assets.
"""

import structlog
import pydantic
from typing import TYPE_CHECKING
from .core import (
    Node,
    GraphState,
    UNRESOLVED,
    InputValueError,
    PropertyField,
    TYPE_CHOICES,
    NodeVerbosity,
    NodeStyle,
)
from .registry import register
from talemate.context import active_scene
from talemate.scene_assets import (
    AssetMeta,
    AssetSelectionContext,
    TAG_MATCH_MODE,
    AssetAttachmentContext,
)
from talemate.agents.visual.schema import (
    VIS_TYPE,
    GEN_TYPE,
    FORMAT_TYPE,
    VIS_TYPE_TO_FORMAT,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene
    from talemate.scene_assets import Asset

log = structlog.get_logger("talemate.game.engine.nodes.assets")

# Node style colors
ASSET_NODE_TITLE_COLOR = "#223040"
ASSET_NODE_COLOR = "#2e4657"

TYPE_CHOICES.extend(
    [
        "asset",
        "asset_meta",
        "asset_attachment_context",
        "asset_selection_context",
    ]
)


@register("assets/AddAsset")
class AddAsset(Node):
    """
    Add an asset to the scene from image data (base64 data URL).

    Inputs:
    - state: graph state (required)
    - image_data: base64 data URL (e.g., "data:image/png;base64,...")
    - meta: asset metadata (optional)
    - asset_attachment_context: controls automatic asset attachment behavior (optional)

    Outputs:
    - state: graph state
    - asset: the created asset object
    - asset_id: the asset ID
    - image_data: the image data (passed through)
    - meta: the asset metadata (passed through)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F0552",  # upload
        )

    class Fields:
        image_data = PropertyField(
            name="image_data",
            description="Base64 data URL (e.g., 'data:image/png;base64,...')",
            type="str",
            default="",
        )

    def __init__(self, title="Add Asset", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("image_data", socket_type="str", optional=True)
        self.add_input("meta", socket_type="asset_meta", optional=True)
        self.add_input(
            "asset_attachment_context",
            socket_type="asset_attachment_context",
            optional=True,
        )

        self.set_property("image_data", "")

        self.add_output("state")
        self.add_output("asset", socket_type="asset")
        self.add_output("asset_id", socket_type="str")
        self.add_output("image_data", socket_type="str")
        self.add_output("meta", socket_type="asset_meta")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        image_data = self.require_input("image_data")
        meta = self.normalized_input_value("meta")
        asset_attachment_context = self.normalized_input_value(
            "asset_attachment_context"
        )

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug(
                "Adding asset",
                image_data=image_data[:50] + "..."
                if len(image_data) > 50
                else image_data,
            )

        try:
            asset = await scene.assets.add_asset_from_image_data(
                image_data, meta, asset_attachment_context
            )
        except ValueError as e:
            raise InputValueError(self, "image_data", str(e))

        scene.emit_status()

        self.set_output_values(
            {
                "state": state,
                "asset": asset,
                "asset_id": asset.id,
                "image_data": image_data,
                "meta": asset.meta,
            }
        )


@register("assets/GetAsset")
class GetAsset(Node):
    """
    Get an asset by ID.

    Inputs:
    - asset_id: the asset ID

    Outputs:
    - asset: the asset object
    - asset_id: the asset ID (passed through)
    - file_type: the file type
    - media_type: the media type
    - meta: the asset metadata
    - asset_bytes: the asset bytes (only set if connected)
    - base64_data: the asset bytes as base64 (only set if connected)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F01DA",  # download
        )

    class Fields:
        asset_id = PropertyField(
            name="asset_id",
            description="The asset ID",
            type="str",
            default="",
        )

    def __init__(self, title="Get Asset", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("asset_id", socket_type="str", optional=True)

        self.set_property("asset_id", "")

        self.add_output("asset", socket_type="asset")
        self.add_output("asset_id", socket_type="str")
        self.add_output("file_type", socket_type="str")
        self.add_output("media_type", socket_type="str")
        self.add_output("meta", socket_type="asset_meta")
        self.add_output("asset_bytes")
        self.add_output("base64_data", socket_type="str")

    def _is_output_connected(self, output_name: str, state: GraphState) -> bool:
        """Check if an output socket is connected to any input socket"""
        output_socket = self.get_output_socket(output_name)
        if not output_socket:
            return False

        output_socket_id = output_socket.full_id

        # Get graph from state
        graph = getattr(state, "graph", None)
        if graph and hasattr(graph, "edges"):
            return (
                output_socket_id in graph.edges
                and len(graph.edges[output_socket_id]) > 0
            )

        return False

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        asset_id = self.normalized_input_value("asset_id")

        if not asset_id:
            return

        try:
            asset: "Asset" = scene.assets.get_asset(asset_id)

            output_values = {
                "asset": asset,
                "asset_id": asset_id,
                "file_type": asset.file_type,
                "media_type": asset.media_type,
                "meta": asset.meta,
            }

            # Only fetch bytes/base64 if the outputs are connected
            if self._is_output_connected("asset_bytes", state):
                asset_bytes = scene.assets.get_asset_bytes(asset_id)
                output_values["asset_bytes"] = asset_bytes

            if self._is_output_connected("base64_data", state):
                base64_data = scene.assets.get_asset_bytes_as_base64(asset_id)
                output_values["base64_data"] = base64_data

            self.set_output_values(output_values)
        except KeyError:
            raise InputValueError(self, "asset_id", f"Asset not found: {asset_id}")


@register("assets/GetAssets")
class GetAssets(Node):
    """
    Get multiple assets by their IDs.

    Inputs:
    - asset_ids: list of asset IDs

    Outputs:
    - assets: list of asset objects
    - asset_ids: list of asset IDs (passed through)
    - asset_count: number of assets retrieved
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F01DA",  # download
        )

    class Fields:
        asset_ids = PropertyField(
            name="asset_ids",
            description="List of asset IDs",
            type="list",
            default=[],
        )

    def __init__(self, title="Get Assets", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("asset_ids", socket_type="list", optional=True)

        self.set_property("asset_ids", [])

        self.add_output("assets", socket_type="list")
        self.add_output("asset_ids", socket_type="list")
        self.add_output("asset_count", socket_type="int")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        asset_ids = self.normalized_input_value("asset_ids")

        # Normalize to list if needed
        if not isinstance(asset_ids, list):
            asset_ids = []

        # Get the actual asset objects
        assets = []
        valid_asset_ids = []

        for asset_id in asset_ids:
            try:
                asset: "Asset" = scene.assets.get_asset(asset_id)
                assets.append(asset)
                valid_asset_ids.append(asset_id)
            except KeyError:
                if state.verbosity >= NodeVerbosity.VERBOSE:
                    log.debug("Asset not found, skipping", asset_id=asset_id)
                # Skip missing assets rather than failing

        self.set_output_values(
            {
                "assets": assets,
                "asset_ids": valid_asset_ids,
                "asset_count": len(assets),
            }
        )


@register("assets/AssetExists")
class AssetExists(Node):
    """
    Check if an asset exists by ID.

    Routes to 'yes' output if the asset exists, 'no' output if it doesn't.

    Inputs:
    - asset_id: the asset ID to check

    Outputs:
    - yes: activated if asset exists (contains asset_id)
    - no: activated if asset does not exist (contains asset_id)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F0641",  # check-circle (same as Switch)
        )

    class Fields:
        asset_id = PropertyField(
            name="asset_id",
            description="The asset ID to check",
            type="str",
            default="",
        )
        return_bool = PropertyField(
            name="return_bool",
            description="If True, return True instead of asset_id",
            type="bool",
            default=False,
        )

    def __init__(self, title="Asset Exists", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("asset_id", socket_type="str", optional=True)

        self.set_property("asset_id", "")
        self.set_property("return_bool", False)

        self.add_output("yes")
        self.add_output("no")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        asset_id = self.require_input("asset_id")
        return_bool = self.get_property("return_bool")

        # Check if asset exists
        asset_exists = asset_id in scene.assets.assets

        # Determine the value to return based on return_bool
        if return_bool:
            yes_value = True if asset_exists else UNRESOLVED
            no_value = True if not asset_exists else UNRESOLVED
        else:
            yes_value = asset_id if asset_exists else UNRESOLVED
            no_value = asset_id if not asset_exists else UNRESOLVED

        self.set_output_values(
            {
                "yes": yes_value,
                "no": no_value,
            }
        )

        # Deactivate the inactive output socket
        self.get_output_socket("yes").deactivated = not asset_exists
        self.get_output_socket("no").deactivated = asset_exists


@register("assets/RemoveAsset")
class RemoveAsset(Node):
    """
    Remove an asset from the scene.

    Inputs:
    - state: graph state (required)
    - asset_id: the asset ID to remove

    Outputs:
    - state: graph state
    - asset_id: the asset ID (passed through)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F01B4",  # delete
        )

    class Fields:
        asset_id = PropertyField(
            name="asset_id",
            description="The asset ID to remove",
            type="str",
            default="",
        )

    def __init__(self, title="Remove Asset", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("asset_id", socket_type="str", optional=True)

        self.set_property("asset_id", "")

        self.add_output("state")
        self.add_output("asset_id", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        asset_id = self.require_input("asset_id")

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug("Removing asset", asset_id=asset_id)

        scene.assets.remove_asset(asset_id)

        self.set_output_values(
            {
                "state": state,
                "asset_id": asset_id,
            }
        )


@register("assets/ListAssets")
class ListAssets(Node):
    """
    List all asset IDs in the scene.

    Outputs:
    - asset_ids: list of asset IDs
    - asset_count: number of assets
    """

    class Fields:
        reference_only = PropertyField(
            name="reference_only",
            description="If True, only return reference assets",
            type="bool",
            default=False,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F0279",  # format-list-bulleted
        )

    def __init__(self, title="List Assets", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("reference_only", False)

        self.add_output("asset_ids", socket_type="list")
        self.add_output("asset_count", socket_type="int")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        reference_only = self.get_property("reference_only")

        asset_ids = []

        for asset_id, asset in scene.assets.assets.items():
            if reference_only and not asset.meta.reference:
                continue
            asset_ids.append(asset_id)

        self.set_output_values(
            {
                "asset_ids": asset_ids,
                "asset_count": len(asset_ids),
            }
        )


@register("assets/SearchAssets")
class SearchAssets(Node):
    """
    Search assets by vis_type, character_name, tags, or reference vis_types.

    Inputs:
    - vis_type: visual type to filter by (can be a single value or a list of values)
    - character_name: character name to filter by (case insensitive)
    - tags: list of tags to filter by (case insensitive)
    - reference_vis_types: list of vis_types to filter by. Only return assets that have at least one matching vis_type in their reference list
    - tag_match_mode: how to match tags - "all" (must have all), "any" (must have at least one), "none" (must not have any)

    Outputs:
    - asset_ids: list of matching asset IDs
    - asset_count: number of matching assets
    - vis_type: visual type filter (passed through)
    - character_name: character name filter (passed through)
    - tags: tags filter (passed through)
    - reference_vis_types: reference vis_types filter (passed through)
    - tag_match_mode: tag match mode (passed through)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F0232",  # filter
        )

    class Fields:
        vis_type = PropertyField(
            name="vis_type",
            description="Visual type to filter by",
            type="str",
            default="",
            choices=VIS_TYPE.choice_values() + ["ANY"],
        )
        character_name = PropertyField(
            name="character_name",
            description="Character name to filter by (case insensitive)",
            type="str",
            default="",
        )
        tags = PropertyField(
            name="tags",
            description="List of tags to filter by (case insensitive)",
            type="list",
            default=[],
        )
        reference_vis_types = PropertyField(
            name="reference_vis_types",
            description="List of vis_types to filter by. Only return assets that have at least one matching vis_type in their reference list",
            type="list",
            default=[],
        )
        tag_match_mode = PropertyField(
            name="tag_match_mode",
            description="How to match tags: 'all' (must have all), 'any' (must have at least one), 'none' (must not have any)",
            type="str",
            default=TAG_MATCH_MODE.ALL.value,
            choices=[
                TAG_MATCH_MODE.ALL.value,
                TAG_MATCH_MODE.ANY.value,
                TAG_MATCH_MODE.NONE.value,
            ],
        )

    def __init__(self, title="Search Assets", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("vis_type", optional=True)
        self.add_input("character_name", socket_type="str", optional=True)
        self.add_input("tags", socket_type="list", optional=True)
        self.add_input("reference_vis_types", socket_type="list", optional=True)

        # Set properties with defaults
        self.set_property("vis_type", "")
        self.set_property("character_name", "")
        self.set_property("tags", [])
        self.set_property("reference_vis_types", [])
        self.set_property("tag_match_mode", TAG_MATCH_MODE.ALL.value)

        # Outputs
        self.add_output("asset_ids", socket_type="list")
        self.add_output("asset_count", socket_type="int")
        self.add_output("vis_type")
        self.add_output("character_name", socket_type="str")
        self.add_output("tags", socket_type="list")
        self.add_output("reference_vis_types", socket_type="list")
        self.add_output("tag_match_mode", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()

        # Get filter values
        vis_type_filter = self.normalized_input_value("vis_type")
        character_name_filter = self.normalized_input_value("character_name")
        tags_filter = self.normalized_input_value("tags")
        reference_vis_types_filter = self.normalized_input_value("reference_vis_types")
        tag_match_mode_str = (
            self.get_property("tag_match_mode") or TAG_MATCH_MODE.ALL.value
        )

        # Validate vis_type if provided - can be a single value or a list
        vis_type_enum = None
        if vis_type_filter and vis_type_filter != "ANY":
            # Handle list of vis_types
            if isinstance(vis_type_filter, list):
                vis_type_enum = []
                for vt in vis_type_filter:
                    if vt and vt != "ANY":
                        try:
                            vis_type_enum.append(VIS_TYPE(vt))
                        except (ValueError, TypeError):
                            raise InputValueError(
                                self,
                                "vis_type",
                                f"Invalid vis_type: {vt}. Must be one of {[v.value for v in VIS_TYPE]}",
                            )
                # If empty after filtering, set to None
                if not vis_type_enum:
                    vis_type_enum = None
            else:
                # Handle single vis_type
                try:
                    vis_type_enum = VIS_TYPE(vis_type_filter)
                except (ValueError, TypeError):
                    raise InputValueError(
                        self,
                        "vis_type",
                        f"Invalid vis_type: {vis_type_filter}. Must be one of {[v.value for v in VIS_TYPE]}",
                    )

        # Normalize tags filter
        if tags_filter and not isinstance(tags_filter, list):
            tags_filter = []

        # Normalize and validate reference_vis_types filter
        reference_vis_types_enum = None
        if reference_vis_types_filter:
            try:
                reference_vis_types_enum = [
                    VIS_TYPE(ref) for ref in reference_vis_types_filter if ref
                ]
            except (ValueError, TypeError):
                raise InputValueError(
                    self,
                    "reference_vis_types",
                    f"Invalid reference_vis_types: {reference_vis_types_filter}. Must be a list of valid VIS_TYPE values.",
                )

        # Validate and convert tag_match_mode
        try:
            tag_match_mode = TAG_MATCH_MODE(tag_match_mode_str)
        except (ValueError, TypeError):
            raise InputValueError(
                self,
                "tag_match_mode",
                f"Invalid tag_match_mode: {tag_match_mode_str}. Must be one of {[m.value for m in TAG_MATCH_MODE]}",
            )

        # Search assets using SceneAssets method
        matching_asset_ids = scene.assets.search_assets(
            vis_type=vis_type_enum,
            character_name=character_name_filter,
            tags=tags_filter,
            tag_match_mode=tag_match_mode,
            reference_vis_types=reference_vis_types_enum,
        )

        self.set_output_values(
            {
                "asset_ids": matching_asset_ids,
                "asset_count": len(matching_asset_ids),
                "vis_type": vis_type_filter or "",
                "character_name": character_name_filter or "",
                "tags": tags_filter or [],
                "reference_vis_types": reference_vis_types_filter or [],
                "tag_match_mode": tag_match_mode.value,
            }
        )


@register("assets/MakeAssetMeta")
class MakeAssetMeta(Node):
    """
    Create an asset metadata object.

    Inputs:
    - name: asset name
    - vis_type: visual type
    - gen_type: generation type
    - character_name: character name
    - prompt: prompt text
    - negative_prompt: negative prompt text
    - sampler_settings: sampler settings object
    - reference_assets: list of reference asset IDs
    - tags: list of tags
    - reference: list of vis_types that this asset may be used as a reference for

    Outputs:
    - meta: the asset metadata object
    - name: asset name (passed through)
    - vis_type: visual type (passed through)
    - gen_type: generation type (passed through)
    - format: recommended format based on vis_type (PORTRAIT, LANDSCAPE, or SQUARE)
    - character_name: character name (passed through)
    - prompt: prompt text (passed through)
    - negative_prompt: negative prompt text (passed through)
    - sampler_settings: sampler settings object (passed through)
    - reference_assets: list of reference asset IDs (passed through)
    - tags: list of tags (passed through)
    - reference: list of vis_types that this asset may be used as a reference for (passed through)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F04F9",  # tag
        )

    class Fields:
        name = PropertyField(
            name="name",
            description="Asset name",
            type="str",
            default="",
        )
        vis_type = PropertyField(
            name="vis_type",
            description="Visual type",
            type="str",
            default="CHARACTER_CARD",
            choices=VIS_TYPE.choice_values(),
        )
        gen_type = PropertyField(
            name="gen_type",
            description="Generation type",
            type="str",
            default="TEXT_TO_IMAGE",
            choices=GEN_TYPE.choice_values(),
        )
        character_name = PropertyField(
            name="character_name",
            description="Character name",
            type="str",
            default="",
        )
        prompt = PropertyField(
            name="prompt",
            description="Prompt text",
            type="text",
            default="",
        )
        negative_prompt = PropertyField(
            name="negative_prompt",
            description="Negative prompt text",
            type="text",
            default="",
        )
        reference_assets = PropertyField(
            name="reference_assets",
            description="List of reference asset IDs",
            type="list",
            default=[],
        )
        tags = PropertyField(
            name="tags",
            description="List of tags",
            type="list",
            default=[],
        )
        analysis = PropertyField(
            name="analysis",
            description="Analysis prompt",
            type="text",
            default="",
        )
        reference = PropertyField(
            name="reference",
            description="List of vis_types that this asset may be used as a reference for",
            type="list",
            default=[],
        )

    def __init__(self, title="Make Asset Meta", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("name", socket_type="str", optional=True)
        self.add_input("vis_type", optional=True)
        self.add_input("gen_type", optional=True)
        self.add_input("character_name", socket_type="str", optional=True)
        self.add_input("prompt", socket_type="str", optional=True)
        self.add_input("negative_prompt", socket_type="str", optional=True)
        self.add_input("sampler_settings", optional=True)
        self.add_input("reference_assets", socket_type="list", optional=True)
        self.add_input("tags", socket_type="list", optional=True)
        self.add_input("analysis", socket_type="str", optional=True)
        self.add_input("reference", socket_type="list", optional=True)

        # Set properties with defaults
        self.set_property("name", "")
        self.set_property("vis_type", "")
        self.set_property("gen_type", "")
        self.set_property("character_name", "")
        self.set_property("prompt", "")
        self.set_property("negative_prompt", "")
        self.set_property("reference_assets", [])
        self.set_property("tags", [])
        self.set_property("analysis", "")
        self.set_property("reference", [])

        # Outputs
        self.add_output("meta", socket_type="asset_meta")
        self.add_output("name", socket_type="str")
        self.add_output("vis_type")
        self.add_output("gen_type")
        self.add_output("format")
        self.add_output("character_name", socket_type="str")
        self.add_output("prompt", socket_type="str")
        self.add_output("negative_prompt", socket_type="str")
        self.add_output("sampler_settings")
        self.add_output("reference_assets", socket_type="list")
        self.add_output("tags", socket_type="list")
        self.add_output("analysis", socket_type="str")
        self.add_output("reference", socket_type="list")

    async def run(self, state: GraphState):
        meta = AssetMeta()

        # Get all input values
        name = self.normalized_input_value("name")
        vis_type = self.normalized_input_value("vis_type") or VIS_TYPE.CHARACTER_CARD
        gen_type = self.normalized_input_value("gen_type") or GEN_TYPE.TEXT_TO_IMAGE
        character_name = self.normalized_input_value("character_name")
        prompt = self.normalized_input_value("prompt")
        negative_prompt = self.normalized_input_value("negative_prompt")
        sampler_settings = self.normalized_input_value("sampler_settings")
        reference_assets = self.normalized_input_value("reference_assets")
        tags = self.normalized_input_value("tags")
        analysis = self.normalized_input_value("analysis")
        reference = self.normalized_input_value("reference")

        # Validate enum values
        if vis_type is not None:
            try:
                vis_type = VIS_TYPE(vis_type)
            except (ValueError, TypeError):
                raise InputValueError(
                    self,
                    "vis_type",
                    f"Invalid vis_type: {vis_type}. Must be one of {[v.value for v in VIS_TYPE]}",
                )

        if gen_type is not None:
            try:
                gen_type = GEN_TYPE(gen_type)
            except (ValueError, TypeError):
                raise InputValueError(
                    self,
                    "gen_type",
                    f"Invalid gen_type: {gen_type}. Must be one of {[v.value for v in GEN_TYPE]}",
                )

        # Validate and convert reference vis_types
        reference_vis_types_enum = []
        if reference:
            try:
                reference_vis_types_enum = [VIS_TYPE(ref) for ref in reference if ref]
            except (ValueError, TypeError):
                raise InputValueError(
                    self,
                    "reference",
                    f"Invalid reference vis_types: {reference}. Must be a list of valid VIS_TYPE values.",
                )

        # Set values if provided
        if name:
            meta.name = name

        if vis_type is not None:
            meta.vis_type = vis_type

        if gen_type is not None:
            meta.gen_type = gen_type

        if character_name:
            meta.character_name = character_name

        if prompt:
            meta.prompt = prompt

        if negative_prompt:
            meta.negative_prompt = negative_prompt

        if sampler_settings is not None:
            meta.sampler_settings = sampler_settings

        if reference_assets is not None:
            meta.reference_assets = reference_assets

        if tags is not None:
            meta.tags = tags

        if reference is not None:
            meta.reference = reference_vis_types_enum

        if analysis is not None:
            meta.analysis = analysis

        # Get recommended format based on vis_type
        recommended_format = VIS_TYPE_TO_FORMAT.get(vis_type, FORMAT_TYPE.PORTRAIT)

        # Set all outputs (meta + pass-through)
        self.set_output_values(
            {
                "meta": meta,
                "name": name or "",
                "vis_type": vis_type,
                "gen_type": gen_type,
                "format": recommended_format,
                "character_name": character_name or "",
                "prompt": prompt or "",
                "negative_prompt": negative_prompt or "",
                "sampler_settings": sampler_settings,
                "reference_assets": reference_assets or [],
                "tags": tags or [],
                "reference": reference_vis_types_enum or [],
                "analysis": analysis or "",
            }
        )


@register("assets/UnpackAssetMeta")
class UnpackAssetMeta(Node):
    """
    Unpack an asset metadata object into its properties.

    Inputs:
    - meta: the asset metadata object

    Outputs:
    - meta: the asset metadata object (passed through)
    - name: asset name
    - vis_type: visual type
    - gen_type: generation type
    - character_name: character name
    - prompt: prompt text
    - negative_prompt: negative prompt text
    - format: format type
    - width: image width
    - height: image height
    - sampler_settings: sampler settings object
    - reference_assets: list of reference asset IDs
    - tags: list of tags
    - reference: list of vis_types that this asset may be used as a reference for
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F02FC",  # information
        )

    def __init__(self, title="Unpack Asset Meta", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("meta", socket_type="asset_meta")

        self.add_output("meta", socket_type="asset_meta")
        self.add_output("name", socket_type="str")
        self.add_output("vis_type")
        self.add_output("gen_type")
        self.add_output("character_name", socket_type="str")
        self.add_output("prompt", socket_type="str")
        self.add_output("negative_prompt", socket_type="str")
        self.add_output("format")
        self.add_output("width", socket_type="int")
        self.add_output("height", socket_type="int")
        self.add_output("sampler_settings")
        self.add_output("reference_assets", socket_type="list")
        self.add_output("tags", socket_type="list")
        self.add_output("analysis", socket_type="str")
        self.add_output("reference", socket_type="list")

    async def run(self, state: GraphState):
        meta: AssetMeta = self.get_input_value("meta")

        # Extract width and height from resolution if available
        width = meta.resolution.width if meta.resolution else None
        height = meta.resolution.height if meta.resolution else None

        self.set_output_values(
            {
                "meta": meta,
                "name": meta.name,
                "vis_type": meta.vis_type,
                "gen_type": meta.gen_type,
                "character_name": meta.character_name,
                "prompt": meta.prompt,
                "negative_prompt": meta.negative_prompt,
                "format": meta.format,
                "width": width,
                "height": height,
                "sampler_settings": meta.sampler_settings,
                "reference_assets": meta.reference_assets,
                "tags": meta.tags,
                "reference": meta.reference,
                "analysis": meta.analysis,
            }
        )


@register("assets/MakeAssetAttachmentContext")
class MakeAssetAttachmentContext(Node):
    """
    Create an asset attachment context object.

    This controls how assets are automatically attached to messages when created.

    Inputs:
    - allow_auto_attach: whether to allow automatic attachment of assets to messages
    - allow_override: whether to allow overriding existing message assets
    - delete_old: whether to delete the old asset when replacing a message's asset
    - message_ids: list of specific message IDs to attach to (empty = auto-detect last message)

    Outputs:
    - context: the asset attachment context object
    - allow_auto_attach: whether to allow automatic attachment (passed through)
    - allow_override: whether to allow overriding existing assets (passed through)
    - delete_old: whether to delete old assets (passed through)
    - message_ids: list of message IDs (passed through)

    Note:
    - When message_ids is empty, assets will be attached to the most recent appropriate message
    - When message_ids is provided, assets will only be attached to those specific messages
    - Use allow_override=true to replace existing message assets, false to skip messages that already have assets
    - Use delete_old=true to delete the old asset when replacing (requires allow_override=true)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F0B5B",  # link-variant
        )

    class Fields:
        asset_name = PropertyField(
            name="asset_name",
            description="Name of the asset to save",
            type="str",
            default="",
        )
        tags = PropertyField(
            name="tags",
            description="List of tags to add to the asset",
            type="list",
            default=[],
        )
        allow_auto_attach = PropertyField(
            name="allow_auto_attach",
            description="Allow automatic attachment of assets to messages",
            type="bool",
            default=False,
        )
        allow_override = PropertyField(
            name="allow_override",
            description="Allow overriding existing message assets",
            type="bool",
            default=False,
        )
        delete_old = PropertyField(
            name="delete_old",
            description="Delete old asset when replacing (requires allow_override=true)",
            type="bool",
            default=False,
        )
        message_ids = PropertyField(
            name="message_ids",
            description="List of message IDs to attach to (empty = auto-detect)",
            type="list",
            default=[],
        )
        scene_cover = PropertyField(
            name="scene_cover",
            description="Whether to set the scene cover image",
            type="bool",
            default=False,
        )
        character_cover = PropertyField(
            name="character_cover",
            description="Whether to set the character cover image",
            type="bool",
            default=False,
        )
        override_scene_cover = PropertyField(
            name="override_scene_cover",
            description="Whether to override the scene cover image (requires scene_cover=true)",
            type="bool",
            default=False,
        )
        override_character_cover = PropertyField(
            name="override_character_cover",
            description="Whether to override the character cover image (requires character_cover=true)",
            type="bool",
            default=False,
        )
        default_avatar = PropertyField(
            name="default_avatar",
            description="Whether to set the default avatar image",
            type="bool",
            default=False,
        )
        override_default_avatar = PropertyField(
            name="override_default_avatar",
            description="Whether to override the default avatar image (requires default_avatar=true)",
            type="bool",
            default=False,
        )
        current_avatar = PropertyField(
            name="current_avatar",
            description="Whether to set the current avatar image",
            type="bool",
            default=False,
        )
        override_current_avatar = PropertyField(
            name="override_current_avatar",
            description="Whether to override the current avatar image (requires current_avatar=true)",
            type="bool",
            default=False,
        )

    def __init__(self, title="Make Asset Attachment Context", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("asset_name", socket_type="str", optional=True)
        self.add_input("tags", socket_type="list", optional=True)
        self.add_input("allow_auto_attach", socket_type="bool", optional=True)
        self.add_input("allow_override", socket_type="bool", optional=True)
        self.add_input("delete_old", socket_type="bool", optional=True)
        self.add_input("message_ids", socket_type="list", optional=True)
        self.add_input("scene_cover", socket_type="bool", optional=True)
        self.add_input("character_cover", socket_type="bool", optional=True)
        self.add_input("override_scene_cover", socket_type="bool", optional=True)
        self.add_input("override_character_cover", socket_type="bool", optional=True)
        self.add_input("default_avatar", socket_type="bool", optional=True)
        self.add_input("current_avatar", socket_type="bool", optional=True)
        self.add_input("override_default_avatar", socket_type="bool", optional=True)
        self.add_input("override_current_avatar", socket_type="bool", optional=True)

        self.set_property("asset_name", "")
        self.set_property("tags", [])
        self.set_property("allow_auto_attach", False)
        self.set_property("allow_override", False)
        self.set_property("delete_old", False)
        self.set_property("message_ids", [])
        self.set_property("scene_cover", False)
        self.set_property("character_cover", False)
        self.set_property("override_scene_cover", False)
        self.set_property("override_character_cover", False)
        self.set_property("default_avatar", False)
        self.set_property("current_avatar", False)
        self.set_property("override_default_avatar", False)
        self.set_property("override_current_avatar", False)

        self.add_output("context", socket_type="asset_attachment_context")
        self.add_output("asset_name", socket_type="str")
        self.add_output("tags", socket_type="list")
        self.add_output("allow_auto_attach", socket_type="bool")
        self.add_output("allow_override", socket_type="bool")
        self.add_output("delete_old", socket_type="bool")
        self.add_output("message_ids", socket_type="list")
        self.add_output("scene_cover", socket_type="bool")
        self.add_output("character_cover", socket_type="bool")
        self.add_output("override_scene_cover", socket_type="bool")
        self.add_output("override_character_cover", socket_type="bool")
        self.add_output("default_avatar", socket_type="bool")
        self.add_output("current_avatar", socket_type="bool")
        self.add_output("override_default_avatar", socket_type="bool")
        self.add_output("override_current_avatar", socket_type="bool")

    async def run(self, state: GraphState):
        tags = self.normalized_input_value("tags")
        allow_auto_attach = self.normalized_input_value("allow_auto_attach")
        allow_override = self.normalized_input_value("allow_override")
        delete_old = self.normalized_input_value("delete_old")
        message_ids = self.normalized_input_value("message_ids")
        scene_cover = self.normalized_input_value("scene_cover")
        character_cover = self.normalized_input_value("character_cover")
        override_scene_cover = self.normalized_input_value("override_scene_cover")
        override_character_cover = self.normalized_input_value(
            "override_character_cover"
        )
        asset_name = self.normalized_input_value("asset_name")
        default_avatar = self.normalized_input_value("default_avatar")
        current_avatar = self.normalized_input_value("current_avatar")
        override_default_avatar = self.normalized_input_value("override_default_avatar")
        override_current_avatar = self.normalized_input_value("override_current_avatar")

        context = AssetAttachmentContext(
            asset_name=asset_name,
            tags=tags or [],
            allow_auto_attach=allow_auto_attach,
            allow_override=allow_override,
            delete_old=delete_old,
            message_ids=message_ids or [],
            scene_cover=scene_cover,
            character_cover=character_cover,
            override_scene_cover=override_scene_cover,
            override_character_cover=override_character_cover,
            default_avatar=default_avatar,
            current_avatar=current_avatar,
            override_default_avatar=override_default_avatar,
            override_current_avatar=override_current_avatar,
        )

        self.set_output_values(
            {
                "context": context,
                "asset_name": asset_name,
                "tags": tags or [],
                "allow_auto_attach": allow_auto_attach,
                "allow_override": allow_override,
                "delete_old": delete_old,
                "message_ids": message_ids or [],
                "scene_cover": scene_cover,
                "character_cover": character_cover,
                "override_scene_cover": override_scene_cover,
                "override_character_cover": override_character_cover,
                "default_avatar": default_avatar,
                "current_avatar": current_avatar,
                "override_default_avatar": override_default_avatar,
                "override_current_avatar": override_current_avatar,
            }
        )


@register("assets/SetCoverImage")
class SetCoverImage(Node):
    """
    Set the cover image for a scene or character.
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F0552",  # upload
        )

    class Fields:
        set_on_scene = PropertyField(
            name="set_on_scene",
            description="Whether to set the cover image on the scene",
            type="bool",
            default=False,
        )
        override_scene = PropertyField(
            name="override_scene",
            description="Whether to override the scene cover image",
            type="bool",
            default=False,
        )
        override_character = PropertyField(
            name="override_character",
            description="Whether to override the character cover image",
            type="bool",
            default=False,
        )

    def __init__(self, title="Set Cover Image", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("asset_id", socket_type="str")
        self.add_input("set_on_scene", socket_type="bool", optional=True)
        self.add_input("override_scene", socket_type="bool", optional=True)
        self.add_input("override_character", socket_type="bool", optional=True)
        self.add_input("character", socket_type="character", optional=True)

        self.set_property("asset_id", "")
        self.set_property("set_on_scene", False)
        self.set_property("override_scene", False)
        self.set_property("override_character", False)

        self.add_output("state")
        self.add_output("asset_id", socket_type="str")
        self.add_output("set_on_scene", socket_type="bool")
        self.add_output("override_scene", socket_type="bool")
        self.add_output("override_character", socket_type="bool")
        self.add_output("character", socket_type="character")

    async def run(self, state: GraphState):
        asset_id = self.normalized_input_value("asset_id")
        set_on_scene = self.normalized_input_value("set_on_scene")
        character = self.normalized_input_value("character")
        scene: "Scene" = active_scene.get()
        override_scene = self.normalized_input_value("override_scene")
        override_character = self.normalized_input_value("override_character")
        if set_on_scene:
            await scene.assets.set_scene_cover_image(
                asset_id=asset_id, override=override_scene
            )
        if character:
            await scene.assets.set_character_cover_image(
                character=character,
                asset_id=asset_id,
                override=override_character,
            )

        self.set_output_values(
            {
                "state": state,
                "asset_id": asset_id,
                "set_on_scene": set_on_scene,
                "override_scene": override_scene,
                "override_character": override_character,
                "character": character,
            }
        )


@register("assets/SetAvatarImage")
class SetAvatarImage(Node):
    """
    Set the avatar image for a character (default or current).

    Inputs:
    - state: graph state (required)
    - asset_id: the asset ID to set as avatar
    - character: the character to set the avatar for
    - avatar_type: "default" or "current" (defaults to "default")

    Outputs:
    - state: graph state
    - asset_id: the asset ID (passed through)
    - character: the character (passed through)
    - avatar_type: the avatar type (passed through)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F0552",  # upload
        )

    class Fields:
        avatar_type = PropertyField(
            name="avatar_type",
            description="Type of avatar to set: 'default' or 'current'",
            type="str",
            default="default",
            choices=["default", "current"],
        )

    def __init__(self, title="Set Avatar Image", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("asset_id", socket_type="str")
        self.add_input("character", socket_type="character")
        self.add_input("avatar_type", socket_type="str", optional=True)

        self.set_property("avatar_type", "default")

        self.add_output("state")
        self.add_output("asset_id", socket_type="str")
        self.add_output("character", socket_type="character")
        self.add_output("avatar_type", socket_type="str")

    async def run(self, state: GraphState):
        state = self.require_input("state")
        asset_id = self.require_input("asset_id")
        character = self.require_input("character")
        avatar_type = self.normalized_input_value("avatar_type") or "default"
        scene: "Scene" = active_scene.get()

        # Validate asset_id
        if not scene.assets.validate_asset_id(asset_id):
            raise InputValueError(self, "asset_id", f"Invalid asset_id: {asset_id}")

        # Validate avatar_type
        if avatar_type not in ["default", "current"]:
            raise InputValueError(
                self,
                "avatar_type",
                f"Invalid avatar_type: {avatar_type}. Must be 'default' or 'current'",
            )

        # Set the avatar based on type
        if avatar_type == "current":
            await scene.assets.set_character_current_avatar(
                character=character, asset_id=asset_id, override=True
            )
        else:
            await scene.assets.set_character_avatar(
                character=character, asset_id=asset_id, override=True
            )

        scene.emit_status()

        self.set_output_values(
            {
                "state": state,
                "asset_id": asset_id,
                "character": character,
                "avatar_type": avatar_type,
            }
        )


@register("assets/UpdateMessageAsset")
class UpdateMessageAsset(Node):
    """
    Update the asset_id and asset_type of messages in the scene history

    Inputs:

    - state: graph state (required)
    - message_ids: List of message IDs to update
    - asset_id: The new asset ID
    - asset_type: The type of asset (e.g., "avatar")

    Properties:

    - asset_type: The type of asset (predefined choices)

    Outputs:

    - state: graph state
    - messages: List of updated message objects
    - message_ids: List of message IDs (passthrough)
    - asset_id: The asset ID (passthrough)
    - asset_type: The asset type (passthrough)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F0287",
        )

    class Fields:
        asset_type = PropertyField(
            name="asset_type",
            description="The type of asset",
            type="str",
            default="avatar",
            choices=["avatar", "card", "scene_illustration", "__keep__"],
        )

    def __init__(self, title="Update Message Assets", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("message_ids", socket_type="list", optional=True)
        self.add_input("asset_id", socket_type="str")

        self.set_property("asset_type", "avatar")

        self.add_output("state")
        self.add_output("messages", socket_type="list")
        self.add_output("message_ids", socket_type="list")
        self.add_output("asset_id", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        state = self.require_input("state")
        message_ids = self.normalized_input_value("message_ids") or []
        asset_id = self.get_input_value("asset_id")

        if not isinstance(asset_id, str):
            raise InputValueError(self, "asset_id", "Asset ID must be a string")

        if not isinstance(message_ids, list):
            raise InputValueError(self, "message_ids", "Message IDs must be a list")

        # Process all messages
        messages = []
        for message_id in message_ids:
            try:
                message = await scene.assets.update_message_asset(
                    message_id=message_id,
                    asset_id=asset_id,
                )
                # Skip messages that aren't found
                if message is not None:
                    messages.append(message)
            except ValueError as e:
                raise InputValueError(self, "asset_id", str(e))

        self.set_output_values(
            {
                "state": state,
                "messages": messages,
                "message_ids": message_ids,
                "asset_id": asset_id,
            }
        )


@register("assets/SelectAssets")
class SelectAssets(Node):
    """
    Select assets from a list of asset IDs by filtering on vis_type and/or reference_vis_types.

    This node is designed to be chained with other SelectAssets nodes to implement
    priority-based selection.

    Modes:
    - noop: Once a selection is made, subsequent nodes pass through the previous selection
    - prioritize: All nodes contribute, results sorted by priority (earlier selections first)

    Example usage (noop mode - fallback):
    1. SearchAssets (CHARACTER_PORTRAIT, CHARACTER_CARD) -> asset_ids
    2. SelectAssets (vis_types=CHARACTER_PORTRAIT) -> tries to select portraits first
    3. SelectAssets (vis_types=CHARACTER_CARD) -> falls back to cards if no portraits

    Example usage (prioritize mode - sorting):
    1. SearchAssets (CHARACTER_PORTRAIT, CHARACTER_CARD) -> asset_ids
    2. SelectAssets (mode=prioritize, vis_types=CHARACTER_PORTRAIT) -> portraits first
    3. SelectAssets (vis_types=CHARACTER_CARD) -> cards added after portraits

    Inputs:
    - asset_ids: list of asset IDs to filter from (only used on first node in chain)
    - selection_context: optional context from previous SelectAssets node
    - vis_types: list of vis_types to match (asset must match any)
    - reference_vis_types: list of reference vis_types to match (asset must have any in its reference list)

    Outputs:
    - asset_ids: list of selected asset IDs
    - asset_count: number of selected assets
    - selection_context: updated context to pass to next SelectAssets node (includes original_asset_ids)
    - selected: whether this node made a selection
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F0232",  # filter
        )

    class Fields:
        mode = PropertyField(
            name="mode",
            description="Selection mode: 'noop' (stop after first match) or 'prioritize' (accumulate and sort by priority)",
            type="str",
            default="noop",
            choices=["noop", "prioritize"],
        )
        vis_types = PropertyField(
            name="vis_types",
            description="List of vis_types to match (asset must match any)",
            type="list",
            default=[],
        )
        reference_vis_types = PropertyField(
            name="reference_vis_types",
            description="List of reference vis_types to match (asset must have any in its reference list)",
            type="list",
            default=[],
        )

    def __init__(self, title="Select Assets", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("asset_ids", socket_type="list", group="input")
        self.add_input(
            "selection_context", socket_type="asset_selection_context", group="input"
        )
        self.add_input("vis_types", socket_type="list", optional=True)
        self.add_input("reference_vis_types", socket_type="list", optional=True)

        self.set_property("mode", "noop")
        self.set_property("vis_types", [])
        self.set_property("reference_vis_types", [])

        self.add_output("asset_ids", socket_type="list")
        self.add_output("asset_count", socket_type="int")
        self.add_output("selection_context", socket_type="asset_selection_context")
        self.add_output("selected", socket_type="bool")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()

        asset_ids = self.normalized_input_value("asset_ids") or []
        selection_context = self.normalized_input_value("selection_context")
        vis_types_filter = self.normalized_input_value("vis_types") or []
        reference_vis_types_filter = (
            self.normalized_input_value("reference_vis_types") or []
        )
        mode = self.get_property("mode") or "noop"

        # If no context provided, create a new one with the mode and original asset_ids
        if selection_context is None:
            selection_context = AssetSelectionContext(
                mode=mode, original_asset_ids=asset_ids
            )

        # Check if we should skip (noop mode with existing selection)
        if selection_context.should_skip():
            self.set_output_values(
                {
                    "asset_ids": selection_context.selected_asset_ids,
                    "asset_count": len(selection_context.selected_asset_ids),
                    "selection_context": selection_context,
                    "selected": False,
                }
            )
            return

        # Validate and convert vis_types
        vis_types_enum: list[VIS_TYPE] = []
        for vt in vis_types_filter:
            if vt:
                try:
                    vis_types_enum.append(VIS_TYPE(vt))
                except (ValueError, TypeError):
                    raise InputValueError(
                        self,
                        "vis_types",
                        f"Invalid vis_type: {vt}. Must be one of {[v.value for v in VIS_TYPE]}",
                    )

        # Validate and convert reference_vis_types
        reference_vis_types_enum: list[VIS_TYPE] = []
        for rvt in reference_vis_types_filter:
            if rvt:
                try:
                    reference_vis_types_enum.append(VIS_TYPE(rvt))
                except (ValueError, TypeError):
                    raise InputValueError(
                        self,
                        "reference_vis_types",
                        f"Invalid reference_vis_type: {rvt}. Must be one of {[v.value for v in VIS_TYPE]}",
                    )

        # Filter out already selected assets (for prioritize mode)
        # Use original_asset_ids from context so all nodes in chain work from the same source
        candidates = selection_context.filter_already_selected(
            selection_context.original_asset_ids
        )

        # Use SceneAssets.select_assets for filtering
        matched_asset_ids = scene.assets.select_assets(
            asset_ids=candidates,
            vis_types=vis_types_enum or None,
            reference_vis_types=reference_vis_types_enum or None,
        )

        # Update context and get output
        made_selection = len(matched_asset_ids) > 0
        output_asset_ids = selection_context.get_output_asset_ids(matched_asset_ids)
        updated_context = selection_context.update_with_matches(matched_asset_ids)

        self.set_output_values(
            {
                "asset_ids": output_asset_ids,
                "asset_count": len(output_asset_ids),
                "selection_context": updated_context,
                "selected": made_selection,
            }
        )


@register("assets/UnpackAssetSelectionContext")
class UnpackAssetSelectionContext(Node):
    """
    Unpack an asset selection context into its properties.

    Inputs:
    - selection_context: the asset selection context object

    Outputs:
    - selection_context: the context object (passed through)
    - mode: selection mode ("noop" or "prioritize")
    - selected: whether any selection has been made
    - asset_ids: list of selected asset IDs
    - asset_count: number of selected assets
    - original_asset_ids: list of original asset IDs passed to first SelectAssets node
    - assets: list of asset objects (only computed if connected)
    - first: first asset object (only set if asset_ids is not empty)
    - last: last asset object (only set if asset_ids is not empty)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color=ASSET_NODE_TITLE_COLOR,
            node_color=ASSET_NODE_COLOR,
            icon="F02FC",  # information
        )

    def __init__(self, title="Unpack Asset Selection Context", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("selection_context", socket_type="asset_selection_context")

        self.add_output("selection_context", socket_type="asset_selection_context")
        self.add_output("mode", socket_type="str")
        self.add_output("selected", socket_type="bool")
        self.add_output("asset_ids", socket_type="list")
        self.add_output("asset_count", socket_type="int")
        self.add_output("original_asset_ids", socket_type="list")
        self.add_output("assets", socket_type="list")
        self.add_output("first", socket_type="asset")
        self.add_output("last", socket_type="asset")

    def _is_output_connected(self, output_name: str, state: GraphState) -> bool:
        """Check if an output socket is connected to any input socket"""
        output_socket = self.get_output_socket(output_name)
        if not output_socket:
            return False

        output_socket_id = output_socket.full_id

        graph = getattr(state, "graph", None)
        if graph and hasattr(graph, "edges"):
            return (
                output_socket_id in graph.edges
                and len(graph.edges[output_socket_id]) > 0
            )

        return False

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        selection_context: AssetSelectionContext = self.get_input_value(
            "selection_context"
        )

        asset_ids = selection_context.selected_asset_ids

        output_values = {
            "selection_context": selection_context,
            "mode": selection_context.mode,
            "selected": selection_context.selected,
            "asset_ids": asset_ids,
            "asset_count": selection_context.asset_count,
            "original_asset_ids": selection_context.original_asset_ids,
        }

        if asset_ids:
            # Get first and last assets
            try:
                output_values["first"] = scene.assets.get_asset(asset_ids[0])
            except KeyError:
                pass

            try:
                output_values["last"] = scene.assets.get_asset(asset_ids[-1])
            except KeyError:
                pass

            # Only compute assets list if the output is connected
            if self._is_output_connected("assets", state):
                assets = []
                for asset_id in asset_ids:
                    try:
                        assets.append(scene.assets.get_asset(asset_id))
                    except KeyError:
                        pass
                output_values["assets"] = assets

        self.set_output_values(output_values)
