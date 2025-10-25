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
    Validate the truthyness of a value

    '', null are considered false
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
    Validate the value is not set
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
    Validate the value is contained in a list or dictionary
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
    Validate the value is a context ID string
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
    Validate the value is a context ID item
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
    Validate the value is a character
    """

    class Fields(ValidateNode.Fields):
        character_status = PropertyField(
            name="character_status",
            description="The status of the character",
            type="str",
            default="all",
            choices=["active", "inactive", "all"],
        )

    def __init__(self, title="Validate Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_output("character", socket_type="character")
        self.set_property("character_status", "all")

    async def run_validation(self, value: Any, state: GraphState):
        character_name: str = value
        scene: "Scene" = active_scene.get()
        character = scene.get_character(character_name)

        allowed_status = self.normalized_input_value("character_status")

        if not character:
            err_msg = self.make_error_message(
                value, "Character `{value}` does not exist"
            )
            log.debug("Character does not exist", value=value, err_msg=err_msg)
            raise InputValueError(self, "value", err_msg)

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
