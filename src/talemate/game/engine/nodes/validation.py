from typing import TYPE_CHECKING, Any
import structlog
import pydantic
from talemate.context import active_scene

from talemate.game.engine.nodes.core import (
    Node,
    register,
    GraphState,
    UNRESOLVED,
    NodeStyle,
    PropertyField,
    InputValueError,
)

from talemate.game.engine.context_id import (
    context_id_handler_from_string,
    ContextIDValidationError,
    context_id_item_from_string,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.game.engine.nodes.validation")


class ValidateNode(Node):
    """
    Base node class for validation nodes
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#461515",
            icon="F046D",  # ruler
        )

    class Fields:
        error_message = PropertyField(
            name="error_message",
            type="str",
            default="",
            description="The error message to raise. Use {value} to reference the value that is not set.",
        )

    def __init__(self, title="Validate", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("value", socket_type="any")
        self.add_input("error_message", socket_type="str", optional=True)
        self.add_output("value", socket_type="any")
        self.set_property("error_message", "")

    def make_error_message(self, value: Any, default: str):
        if not self.normalized_input_value("error_message"):
            return default.format(value=value)
        return self.normalized_input_value("error_message").format(value=value)

    async def run_validation(self, value: Any, state: GraphState):
        pass

    async def run(self, state: GraphState):
        value = self.get_input_value("value")
        value = await self.run_validation(value, state)
        self.set_output_values({"value": value})


@register("validation/ValidateValueIsSet")
class ValidateValueIsSet(ValidateNode):
    """
    Validate that a value is set, raising an error if it isn't.

    A value counts as unset when it is null, unresolved or - when
    `blank_string_is_unset` is true - a blank string. Other falsy values
    (0, false) count as set. On success the value is passed through.

    Inputs:

    - value: The value to validate
    - error_message: Custom error message, `{value}` is replaced with the value (optional)

    Properties:

    - blank_string_is_unset: If true, a blank string is considered unset

    Outputs:

    - value: The validated value, passed through
    """

    class Fields(ValidateNode.Fields):
        blank_string_is_unset = PropertyField(
            name="blank_string_is_unset",
            type="bool",
            default=True,
            description="If true, a blank string will be considered unset",
        )

    def __init__(self, title="Validate Value Is Set", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.set_property("blank_string_is_unset", True)

    async def run_validation(self, value: Any, state: GraphState):
        is_none = value is None
        is_unresolved = value is UNRESOLVED
        is_blank_string = self.get_property("blank_string_is_unset") and value == ""

        if is_none or is_unresolved or is_blank_string:
            err_msg = self.make_error_message(value, "Value is not set")
            log.debug("Value is not set", value=value, err_msg=err_msg)
            raise InputValueError(self, "value", err_msg)
        return value


@register("validation/ValidateValueIsNotSet")
class ValidateValueIsNotSet(ValidateNode):
    """
    Validate that a value is NOT set, raising an error if it is.

    A value counts as unset when it is null, unresolved or a blank string.

    Inputs:

    - value: The value to validate
    - error_message: Custom error message, `{value}` is replaced with the value (optional)

    Outputs:

    - value: The (unset) value, passed through
    """

    def __init__(self, title="Validate Value Is Not Set", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()

    async def run_validation(self, value: Any, state: GraphState):
        if value is None or value is UNRESOLVED or value == "":
            return value

        err_msg = self.make_error_message(value, "Value is set")
        log.debug("Value is set", value=value, err_msg=err_msg)
        raise InputValueError(self, "value", err_msg)


@register("validation/ValidateValueContained")
class ValidateValueContained(ValidateNode):
    """
    Validate that a value is contained in a list or dictionary, raising an
    error if it isn't.

    For dictionaries, containment is checked against the keys.

    Inputs:

    - value: The value to validate
    - error_message: Custom error message, `{value}` is replaced with the value (optional)
    - list: The list or dictionary to check containment against

    Outputs:

    - value: The validated value, passed through
    """

    def __init__(self, title="Validate Value Contained", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_input("list", socket_type="list,dict")

    async def run_validation(self, value: Any, state: GraphState):
        target_list = self.get_input_value("list")
        if value not in target_list:
            err_msg = self.make_error_message(value, "Value is not contained")
            log.debug("Value is not contained", value=value, err_msg=err_msg)
            raise InputValueError(self, "value", err_msg)
        return value


@register("validation/ValidateContextIDString")
class ValidateContextIDString(ValidateNode):
    """
    Validate that a value is a valid context ID string, raising an error if it
    isn't.

    Surrounding backticks and whitespace are stripped before validation, and
    the cleaned string is passed through on success.

    Inputs:

    - value: The context ID string to validate
    - error_message: Custom error message, `{value}` is replaced with the value (optional)

    Outputs:

    - value: The cleaned, validated context ID string
    """

    def __init__(self, title="Validate Context ID String", **kwargs):
        super().__init__(title=title, **kwargs)

    async def run_validation(self, value: str | Any, state: GraphState):
        scene: "Scene" = active_scene.get()

        try:
            value = value.strip("`").strip()
        except Exception:
            typ_name = type(value).__name__
            raise InputValueError(self, "value", f"Invalid type: {typ_name}")

        try:
            await context_id_handler_from_string(value, scene)
        except ContextIDValidationError as e:
            err_msg = self.make_error_message(value, str(e))
            log.debug("Invalid context ID string", value=value, err_msg=err_msg)
            raise InputValueError(self, "value", err_msg)

        return value


@register("validation/ValidateContextIDItem")
class ValidateContextIDItem(ValidateNode):
    """
    Validate that a value is a context ID string that resolves to an existing
    context ID item, raising an error if it doesn't.

    Surrounding backticks and whitespace are stripped before validation. On
    success the resolved item and its details are provided as outputs.

    Inputs:

    - value: The context ID string to validate and resolve
    - error_message: Custom error message, `{value}` is replaced with the value (optional)

    Outputs:

    - value: The cleaned, validated context ID string
    - context_id: The context ID of the resolved item
    - context_id_item: The resolved context ID item
    - context_type: The context type of the resolved item
    - context_value: The current value stored at the context ID
    - name: The name of the resolved item
    """

    def __init__(self, title="Validate Context ID Item", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_output("context_id", socket_type="context_id")
        self.add_output("context_id_item", socket_type="context_id_item")
        self.add_output("context_type", socket_type="str")
        self.add_output("context_value", socket_type="any")
        self.add_output("name", socket_type="str")

    async def run_validation(self, value: str | Any, state: GraphState):
        scene: "Scene" = active_scene.get()

        try:
            value = value.strip("`").strip()
        except Exception:
            typ_name = type(value).__name__
            raise InputValueError(self, "value", f"Invalid type: {typ_name}")

        try:
            context_id_item = await context_id_item_from_string(value, scene)
        except ContextIDValidationError as e:
            err_msg = self.make_error_message(value, str(e))
            log.debug("Invalid context ID item", value=value, err_msg=err_msg)
            raise InputValueError(self, "value", err_msg)

        if not context_id_item:
            err_msg = self.make_error_message(
                value, f"Context ID item not found: {value}"
            )
            log.debug("Context ID item not found", value=value, err_msg=err_msg)
            raise InputValueError(self, "value", err_msg)

        self.set_output_values(
            {
                "context_id_item": context_id_item,
                "context_id": context_id_item.context_id,
                "context_type": context_id_item.context_id.context_type,
                "context_value": await context_id_item.get(scene),
                "name": context_id_item.name,
            }
        )

        return value


@register("validation/ValidateCharacter")
class ValidateCharacter(ValidateNode):
    """
    Validate that a value is the name of a character in the scene, raising an
    error if it isn't.

    Optionally restrict to active or inactive characters, or create a
    placeholder character when the name doesn't exist.

    Inputs:

    - value: The character name to validate
    - error_message: Custom error message, `{value}` is replaced with the value (optional)

    Properties:

    - character_status: Which characters are allowed (active, inactive, or all)
    - create_placeholder: Whether to create a placeholder character if the character does not exist

    Outputs:

    - value: The validated character name, passed through
    - character: The character object (or placeholder)
    """

    class Fields(ValidateNode.Fields):
        character_status = PropertyField(
            name="character_status",
            description="The status of the character",
            type="str",
            default="all",
            choices=["active", "inactive", "all"],
        )
        create_placeholder = PropertyField(
            name="create_placeholder",
            description="Whether to create a placeholder character if the character does not exist",
            type="bool",
            default=False,
        )

    def __init__(self, title="Validate Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_output("character", socket_type="character")
        self.set_property("character_status", "all")
        self.set_property("create_placeholder", False)

    async def run_validation(self, value: Any, state: GraphState):
        character_name: str = value
        scene: "Scene" = active_scene.get()
        character = scene.get_character(character_name)
        create_placeholder = self.normalized_input_value("create_placeholder")

        allowed_status = self.normalized_input_value("character_status")

        if not character and not create_placeholder:
            err_msg = self.make_error_message(
                value, "Character `{value}` does not exist"
            )
            log.debug("Character does not exist", value=value, err_msg=err_msg)
            raise InputValueError(self, "value", err_msg)

        if not character and create_placeholder:
            character = scene.Character(name=character_name)

        if allowed_status == "active" and not scene.character_is_active(character):
            err_msg = self.make_error_message(
                value,
                "Character `{value}` is not active, only active characters are allowed",
            )
            log.debug("Character is not active", value=value, err_msg=err_msg)
            raise InputValueError(self, "value", err_msg)

        if allowed_status == "inactive" and scene.character_is_active(character):
            err_msg = self.make_error_message(
                value,
                "Character `{value}` is active, only inactive characters are allowed",
            )
            log.debug("Character is active", value=value, err_msg=err_msg)
            raise InputValueError(self, "value", err_msg)

        self.set_output_values({"character": character})

        return character_name


@register("validation/ValidateAssetID")
class ValidateAssetID(ValidateNode):
    """
    Validate that a value is the ID of an existing scene asset, raising an
    error if it isn't.

    Inputs:

    - value: The asset ID to validate
    - error_message: Custom error message, `{value}` is replaced with the value (optional)

    Outputs:

    - value: The validated asset ID, passed through
    - asset: The asset object
    """

    def __init__(self, title="Validate Asset ID", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_output("asset", socket_type="asset")

    async def run_validation(self, value: Any, state: GraphState):
        scene: "Scene" = active_scene.get()
        asset_is_valid = scene.assets.validate_asset_id(value)
        if not asset_is_valid:
            err_msg = self.make_error_message(value, "Asset `{value}` does not exist")
            log.debug("Asset does not exist", value=value, err_msg=err_msg)
            raise InputValueError(self, "value", err_msg)

        self.set_output_values({"asset": scene.assets.get_asset(value)})
        return value
