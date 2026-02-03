"""
Response extraction nodes for the node graph system.

Provides nodes for creating response extractors and ResponseSpec instances
that can be used with GenerateResponse to parse LLM outputs.
"""

import re
import structlog
import pydantic

from .core import (
    Node,
    GraphState,
    PropertyField,
    NodeStyle,
)
from .registry import register

from talemate.prompts.response import (
    AsIsExtractor as AsIsExtractorClass,
    AnchorExtractor as AnchorExtractorClass,
    ComplexAnchorExtractor as ComplexAnchorExtractorClass,
    AfterAnchorExtractor as AfterAnchorExtractorClass,
    RegexExtractor as RegexExtractorClass,
    StripPrefixExtractor as StripPrefixExtractorClass,
    CodeBlockExtractor as CodeBlockExtractorClass,
    ComplexCodeBlockExtractor as ComplexCodeBlockExtractorClass,
    ResponseSpec as ResponseSpecClass,
)

log = structlog.get_logger("talemate.game.engine.nodes.response")


# -----------------------------------------------------------------------------
# Base class for extractor nodes
# -----------------------------------------------------------------------------


class ExtractorNodeBase(Node):
    """Base class for extractor nodes with common name input/output pattern."""

    def setup_name_io(self):
        """Set up the common name input/output and property."""
        self.add_input("name", socket_type="str", optional=True)
        self.set_property("name", "")
        self.add_output("name", socket_type="str")
        # Named 'value' so DictCollector can infer key from 'name' property
        self.add_output("value", socket_type="response/extractor")
        # Convenience output: a ResponseSpec with just this extractor
        self.add_output("spec", socket_type="response/spec")

    def get_name_value(self) -> str:
        """Get the name from input or property."""
        return self.get_input_value("name")

    def set_extractor_outputs(self, extractor):
        """Set the common outputs for extractor nodes."""
        name = self.get_name_value()
        spec = ResponseSpecClass(
            extractors={name: extractor},
            required=[name],
        )
        self.set_output_values(
            {
                "name": name,
                "value": extractor,
                "spec": spec,
            }
        )


# -----------------------------------------------------------------------------
# Extractor Nodes
# -----------------------------------------------------------------------------


@register("response/AsIsExtractor")
class AsIsExtractor(ExtractorNodeBase):
    """
    Creates an AsIsExtractor that returns the entire response as-is.

    Properties:
    - name: Key name for DictCollector
    - trim: Whether to trim whitespace (default: True)

    Outputs:
    - name: The extractor name (pass-through)
    - extractor: The AsIsExtractor instance
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="Extractor name (key for dict collector)",
            type="str",
            default="",
        )
        trim = PropertyField(
            name="trim",
            description="Trim whitespace from result",
            type="bool",
            default=True,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(auto_title="AsIs: {name}")

    def __init__(self, title="AsIs Extractor", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.setup_name_io()
        self.set_property("trim", True)

    async def run(self, state: GraphState):
        extractor = AsIsExtractorClass(
            trim=self.get_property("trim"),
        )
        self.set_extractor_outputs(extractor)


@register("response/AnchorExtractor")
class AnchorExtractor(ExtractorNodeBase):
    """
    Creates an AnchorExtractor that extracts content between anchor tags.

    Properties:
    - name: Key name for DictCollector
    - left: Left anchor (e.g., "<MESSAGE>")
    - right: Right anchor (e.g., "</MESSAGE>")
    - fallback_to_full: Return full response if anchors not found
    - trim: Whether to trim whitespace

    Outputs:
    - name: The extractor name (pass-through)
    - extractor: The AnchorExtractor instance
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="Extractor name (key for dict collector)",
            type="str",
            default="",
        )
        left = PropertyField(
            name="left",
            description="Left anchor tag (e.g., <MESSAGE>)",
            type="str",
            default="",
        )
        right = PropertyField(
            name="right",
            description="Right anchor tag (e.g., </MESSAGE>)",
            type="str",
            default="",
        )
        fallback_to_full = PropertyField(
            name="fallback_to_full",
            description="Return full response if anchors not found",
            type="bool",
            default=False,
        )
        trim = PropertyField(
            name="trim",
            description="Trim whitespace from result",
            type="bool",
            default=True,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(auto_title="Anchor: {name}")

    def __init__(self, title="Anchor Extractor", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.setup_name_io()
        self.set_property("left", "")
        self.set_property("right", "")
        self.set_property("fallback_to_full", False)
        self.set_property("trim", True)

    async def run(self, state: GraphState):
        extractor = AnchorExtractorClass(
            left=self.get_property("left"),
            right=self.get_property("right"),
            fallback_to_full=self.get_property("fallback_to_full"),
            trim=self.get_property("trim"),
        )
        self.set_extractor_outputs(extractor)


@register("response/ComplexAnchorExtractor")
class ComplexAnchorExtractor(ExtractorNodeBase):
    """
    Creates a ComplexAnchorExtractor with nesting awareness.

    Tracks multiple tags and only extracts target blocks when at root level.

    Properties:
    - name: Key name for DictCollector
    - left: Left anchor tag
    - right: Right anchor tag
    - tracked_tags: List of tag names to track for nesting
    - fallback_to_full: Return full response if anchors not found
    - trim: Whether to trim whitespace

    Inputs:
    - name: Optional override for name property
    - tracked_tags: Optional override for tracked_tags property

    Outputs:
    - name: The extractor name (pass-through)
    - tracked_tags: The tracked tags list (pass-through)
    - extractor: The ComplexAnchorExtractor instance
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="Extractor name (key for dict collector)",
            type="str",
            default="",
        )
        left = PropertyField(
            name="left",
            description="Left anchor tag (e.g., <MESSAGE>)",
            type="str",
            default="",
        )
        right = PropertyField(
            name="right",
            description="Right anchor tag (e.g., </MESSAGE>)",
            type="str",
            default="",
        )
        tracked_tags = PropertyField(
            name="tracked_tags",
            description="Tags to track for nesting awareness",
            type="list",
            default=[],
        )
        fallback_to_full = PropertyField(
            name="fallback_to_full",
            description="Return full response if anchors not found",
            type="bool",
            default=False,
        )
        trim = PropertyField(
            name="trim",
            description="Trim whitespace from result",
            type="bool",
            default=True,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(auto_title="ComplexAnchor: {name}")

    def __init__(self, title="Complex Anchor Extractor", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.setup_name_io()
        self.add_input("tracked_tags", socket_type="list", optional=True)
        self.set_property("left", "")
        self.set_property("right", "")
        self.set_property("tracked_tags", [])
        self.set_property("fallback_to_full", False)
        self.set_property("trim", True)
        self.add_output("tracked_tags", socket_type="list")

    def get_tracked_tags(self) -> list:
        """Get tracked_tags from input or property."""
        value = self.normalized_input_value("tracked_tags")
        if value is not None:
            return value
        return self.get_property("tracked_tags")

    async def run(self, state: GraphState):
        tracked_tags = self.get_tracked_tags()
        extractor = ComplexAnchorExtractorClass(
            left=self.get_property("left"),
            right=self.get_property("right"),
            tracked_tags=tracked_tags,
            fallback_to_full=self.get_property("fallback_to_full"),
            trim=self.get_property("trim"),
        )
        name = self.get_name_value()
        spec = ResponseSpecClass(
            extractors={name: extractor},
            required=[name],
        )
        self.set_output_values(
            {
                "name": name,
                "tracked_tags": tracked_tags,
                "value": extractor,
                "spec": spec,
            }
        )


@register("response/AfterAnchorExtractor")
class AfterAnchorExtractor(ExtractorNodeBase):
    """
    Creates an AfterAnchorExtractor that extracts everything after a start marker.

    Properties:
    - name: Key name for DictCollector
    - start: Start marker to search for
    - stop_at: Optional end marker (empty string = no stop)
    - fallback_to_full: Return full response if start marker not found
    - trim: Whether to trim whitespace

    Outputs:
    - name: The extractor name (pass-through)
    - extractor: The AfterAnchorExtractor instance
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="Extractor name (key for dict collector)",
            type="str",
            default="",
        )
        start = PropertyField(
            name="start",
            description="Start marker to search for",
            type="str",
            default="",
        )
        stop_at = PropertyField(
            name="stop_at",
            description="Optional end marker (empty = no stop)",
            type="str",
            default="",
        )
        fallback_to_full = PropertyField(
            name="fallback_to_full",
            description="Return full response if start marker not found",
            type="bool",
            default=False,
        )
        trim = PropertyField(
            name="trim",
            description="Trim whitespace from result",
            type="bool",
            default=True,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(auto_title="AfterAnchor: {name}")

    def __init__(self, title="After Anchor Extractor", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.setup_name_io()
        self.set_property("start", "")
        self.set_property("stop_at", "")
        self.set_property("fallback_to_full", False)
        self.set_property("trim", True)

    async def run(self, state: GraphState):
        stop_at = self.get_property("stop_at")
        extractor = AfterAnchorExtractorClass(
            start=self.get_property("start"),
            stop_at=stop_at if stop_at else None,
            fallback_to_full=self.get_property("fallback_to_full"),
            trim=self.get_property("trim"),
        )
        self.set_extractor_outputs(extractor)


@register("response/RegexExtractor")
class RegexExtractor(ExtractorNodeBase):
    """
    Creates a RegexExtractor that extracts content using regex patterns.

    Properties:
    - name: Key name for DictCollector
    - pattern: Regex pattern with capture group
    - case_insensitive: Whether to ignore case
    - group: Capture group to extract (default: 1)
    - all_matches: Return list of all matches instead of first
    - trim: Whether to trim whitespace

    Outputs:
    - name: The extractor name (pass-through)
    - extractor: The RegexExtractor instance
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="Extractor name (key for dict collector)",
            type="str",
            default="",
        )
        pattern = PropertyField(
            name="pattern",
            description="Regex pattern with capture group",
            type="str",
            default="",
        )
        case_insensitive = PropertyField(
            name="case_insensitive",
            description="Ignore case when matching",
            type="bool",
            default=False,
        )
        group = PropertyField(
            name="group",
            description="Capture group to extract",
            type="int",
            default=1,
        )
        all_matches = PropertyField(
            name="all_matches",
            description="Return list of all matches",
            type="bool",
            default=False,
        )
        trim = PropertyField(
            name="trim",
            description="Trim whitespace from result",
            type="bool",
            default=True,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(auto_title="Regex: {name}")

    def __init__(self, title="Regex Extractor", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.setup_name_io()
        self.set_property("pattern", "")
        self.set_property("case_insensitive", False)
        self.set_property("group", 1)
        self.set_property("all_matches", False)
        self.set_property("trim", True)

    async def run(self, state: GraphState):
        flags = re.IGNORECASE if self.get_property("case_insensitive") else 0
        extractor = RegexExtractorClass(
            pattern=self.get_property("pattern"),
            flags=flags,
            group=self.get_property("group"),
            all_matches=self.get_property("all_matches"),
            trim=self.get_property("trim"),
        )
        self.set_extractor_outputs(extractor)


@register("response/StripPrefixExtractor")
class StripPrefixExtractor(ExtractorNodeBase):
    """
    Creates a StripPrefixExtractor that strips patterns using regex substitution.

    Properties:
    - name: Key name for DictCollector
    - pattern: Regex pattern to strip
    - replacement: Replacement string (default: "")
    - trim: Whether to trim whitespace

    Outputs:
    - name: The extractor name (pass-through)
    - extractor: The StripPrefixExtractor instance
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="Extractor name (key for dict collector)",
            type="str",
            default="",
        )
        pattern = PropertyField(
            name="pattern",
            description="Regex pattern to strip",
            type="str",
            default="",
        )
        replacement = PropertyField(
            name="replacement",
            description="Replacement string",
            type="str",
            default="",
        )
        trim = PropertyField(
            name="trim",
            description="Trim whitespace from result",
            type="bool",
            default=True,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(auto_title="StripPrefix: {name}")

    def __init__(self, title="Strip Prefix Extractor", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.setup_name_io()
        self.set_property("pattern", "")
        self.set_property("replacement", "")
        self.set_property("trim", True)

    async def run(self, state: GraphState):
        extractor = StripPrefixExtractorClass(
            pattern=self.get_property("pattern"),
            replacement=self.get_property("replacement"),
            trim=self.get_property("trim"),
        )
        self.set_extractor_outputs(extractor)


@register("response/CodeBlockExtractor")
class CodeBlockExtractor(ExtractorNodeBase):
    """
    Creates a CodeBlockExtractor that extracts code blocks from tagged sections.

    Properties:
    - name: Key name for DictCollector
    - left: Left anchor tag
    - right: Right anchor tag
    - validate_structured: Validate content as JSON/YAML for no-fence fallback
    - fallback_to_full: Return full response if anchors not found
    - trim: Whether to trim whitespace

    Outputs:
    - name: The extractor name (pass-through)
    - extractor: The CodeBlockExtractor instance
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="Extractor name (key for dict collector)",
            type="str",
            default="",
        )
        left = PropertyField(
            name="left",
            description="Left anchor tag (e.g., <ACTIONS>)",
            type="str",
            default="",
        )
        right = PropertyField(
            name="right",
            description="Right anchor tag (e.g., </ACTIONS>)",
            type="str",
            default="",
        )
        validate_structured = PropertyField(
            name="validate_structured",
            description="Validate content as JSON/YAML for no-fence fallback",
            type="bool",
            default=True,
        )
        fallback_to_full = PropertyField(
            name="fallback_to_full",
            description="Return full response if anchors not found",
            type="bool",
            default=False,
        )
        trim = PropertyField(
            name="trim",
            description="Trim whitespace from result",
            type="bool",
            default=True,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(auto_title="CodeBlock: {name}")

    def __init__(self, title="Code Block Extractor", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.setup_name_io()
        self.set_property("left", "")
        self.set_property("right", "")
        self.set_property("validate_structured", True)
        self.set_property("fallback_to_full", False)
        self.set_property("trim", True)

    async def run(self, state: GraphState):
        extractor = CodeBlockExtractorClass(
            left=self.get_property("left"),
            right=self.get_property("right"),
            validate_structured=self.get_property("validate_structured"),
            fallback_to_full=self.get_property("fallback_to_full"),
            trim=self.get_property("trim"),
        )
        self.set_extractor_outputs(extractor)


@register("response/ComplexCodeBlockExtractor")
class ComplexCodeBlockExtractor(ExtractorNodeBase):
    """
    Creates a ComplexCodeBlockExtractor with nesting awareness for code blocks.

    Properties:
    - name: Key name for DictCollector
    - left: Left anchor tag
    - right: Right anchor tag
    - tracked_tags: List of tag names to track for nesting
    - validate_structured: Validate content as JSON/YAML for no-fence fallback
    - fallback_to_full: Return full response if anchors not found
    - trim: Whether to trim whitespace

    Inputs:
    - name: Optional override for name property
    - tracked_tags: Optional override for tracked_tags property

    Outputs:
    - name: The extractor name (pass-through)
    - tracked_tags: The tracked tags list (pass-through)
    - extractor: The ComplexCodeBlockExtractor instance
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="Extractor name (key for dict collector)",
            type="str",
            default="",
        )
        left = PropertyField(
            name="left",
            description="Left anchor tag (e.g., <ACTIONS>)",
            type="str",
            default="",
        )
        right = PropertyField(
            name="right",
            description="Right anchor tag (e.g., </ACTIONS>)",
            type="str",
            default="",
        )
        tracked_tags = PropertyField(
            name="tracked_tags",
            description="Tags to track for nesting awareness",
            type="list",
            default=[],
        )
        validate_structured = PropertyField(
            name="validate_structured",
            description="Validate content as JSON/YAML for no-fence fallback",
            type="bool",
            default=True,
        )
        fallback_to_full = PropertyField(
            name="fallback_to_full",
            description="Return full response if anchors not found",
            type="bool",
            default=False,
        )
        trim = PropertyField(
            name="trim",
            description="Trim whitespace from result",
            type="bool",
            default=True,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(auto_title="ComplexCodeBlock: {name}")

    def __init__(self, title="Complex Code Block Extractor", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.setup_name_io()
        self.add_input("tracked_tags", socket_type="list", optional=True)
        self.set_property("left", "")
        self.set_property("right", "")
        self.set_property("tracked_tags", [])
        self.set_property("validate_structured", True)
        self.set_property("fallback_to_full", False)
        self.set_property("trim", True)
        self.add_output("tracked_tags", socket_type="list")

    def get_tracked_tags(self) -> list:
        """Get tracked_tags from input or property."""
        value = self.normalized_input_value("tracked_tags")
        if value is not None:
            return value
        return self.get_property("tracked_tags")

    async def run(self, state: GraphState):
        tracked_tags = self.get_tracked_tags()
        extractor = ComplexCodeBlockExtractorClass(
            left=self.get_property("left"),
            right=self.get_property("right"),
            tracked_tags=tracked_tags,
            validate_structured=self.get_property("validate_structured"),
            fallback_to_full=self.get_property("fallback_to_full"),
            trim=self.get_property("trim"),
        )
        name = self.get_name_value()
        spec = ResponseSpecClass(
            extractors={name: extractor},
            required=[name],
        )
        self.set_output_values(
            {
                "name": name,
                "tracked_tags": tracked_tags,
                "value": extractor,
                "spec": spec,
            }
        )


# -----------------------------------------------------------------------------
# ResponseSpec Node
# -----------------------------------------------------------------------------


@register("response/ResponseSpec")
class ResponseSpec(Node):
    """
    Creates a ResponseSpec from a dictionary of extractors.

    Properties:
    - required: List of required field names

    Inputs:
    - extractors: Dictionary of name -> Extractor (from DictCollector)
    - required: Optional override for required property

    Outputs:
    - spec: The ResponseSpec instance
    - extractors: Pass-through of the extractors dict
    """

    class Fields:
        required = PropertyField(
            name="required",
            description="List of required field names",
            type="list",
            default=[],
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            icon="F0C17",
            title_color="#4a5568",
        )

    def __init__(self, title="Response Spec", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("extractors", socket_type="dict")
        self.add_input("required", socket_type="list", optional=True)
        self.set_property("required", [])
        self.add_output("spec", socket_type="response/spec")
        self.add_output("extractors", socket_type="dict")

    def get_required(self) -> list:
        """Get required from input or property."""
        value = self.normalized_input_value("required")
        if value is not None:
            return value
        return self.get_property("required")

    async def run(self, state: GraphState):
        extractors = self.require_input("extractors")
        required = self.get_required()

        spec = ResponseSpecClass(
            extractors=extractors,
            required=required,
        )

        self.set_output_values(
            {
                "spec": spec,
                "extractors": extractors,
            }
        )
