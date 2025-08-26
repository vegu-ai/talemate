import random
import json
import structlog
import pydantic
from .core import (
    Node,
    GraphState,
    UNRESOLVED,
    PropertyField,
    InputValueError,
    TYPE_CHOICES,
    NodeStyle,
    NodeVerbosity,
)
from .core.dynamic import DynamicSocketNodeBase
from .registry import register

log = structlog.get_logger("talemate.game.engine.nodes.data")


@register("data/Sort")
class Sort(Node):
    """
    Sorts a list of items

    Inputs:

    - items: List of items to sort
    - sort_keys: List of keys to sort by
    - reverse: Reverse sort

    Properties:

    - sort_keys: List of keys to sort by
    - reverse: Reverse sort

    Outputs:

    - sorted_items: Sorted list of items
    """

    class Fields:
        sort_keys = PropertyField(
            name="sort_keys",
            description="Sort keys",
            type="list",
            default=UNRESOLVED,
        )

        reverse = PropertyField(
            name="reverse",
            description="Reverse sort",
            type="bool",
            default=False,
        )

    def __init__(self, title="Sort", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("items", socket_type="list")
        self.add_input("sort_keys", socket_type=["str", "list"], optional=True)

        self.set_property("reverse", False)
        self.set_property("sort_keys", UNRESOLVED)

        self.add_output("sorted_items", socket_type="list")

    async def run(self, state: GraphState):
        items = self.get_input_value("items")

        sort_keys = self.get_input_value("sort_keys")

        if isinstance(sort_keys, str):
            sort_keys = json.loads(sort_keys)

        if sort_keys != UNRESOLVED and not isinstance(sort_keys, list):
            log.error("Sort keys must be a list", sort_keys=sort_keys)
            raise InputValueError(self, "sort_keys", "Sort keys must be a list")

        new_items = [i for i in items]
        reverse = self.get_property("reverse")
        if self.is_set(sort_keys) and len(sort_keys) > 0:
            new_items.sort(
                key=lambda x: tuple([getattr(x, k, None) for k in sort_keys]),
                reverse=reverse,
            )
        else:
            new_items.sort(reverse=reverse)

        self.set_output_values({"sorted_items": new_items})


@register("data/JSON")
class JSON(Node):
    """
    Node that converts a JSON string to a Python object

    Inputs:

    - json: JSON string

    Outputs:

    - data: Python object (dict or list)
    """

    def __init__(self, title="JSON", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("json", socket_type="str")
        self.add_output("data", socket_type="dict,list")

    async def run(self, state: GraphState):
        json_string = self.get_input_value("json")

        # convert json string to python object
        # support list as root object
        data = json.loads(json_string)
        self.set_output_values({"data": data})


@register("data/Contains")
class Contains(Node):
    """
    Checks if a value is in a list or dictionary

    Inputs:

    - object: Object (list, dict, etc.) - if a generator is provided, it will be converted to a list
    - value: Value

    Outputs:

    - contains: True if value is in object, False otherwise
    """

    class Fields:
        value = PropertyField(
            name="value",
            description="Value",
            type="any",
            default=UNRESOLVED,
        )

    def __init__(self, title="Contains", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("object", socket_type="any")
        self.add_input("value", socket_type="any")

        self.set_property("value", UNRESOLVED)

        self.add_output("contains", socket_type="bool")

    async def run(self, state: GraphState):
        object = self.get_input_value("object")
        value = self.get_input_value("value")

        # If object is a generator, convert it to a list
        if hasattr(object, "__iter__") and not isinstance(object, (dict, list, str)):
            object = list(object)

        contains = False

        # Check if value is in object
        if isinstance(object, dict):
            contains = value in object
        elif isinstance(object, (list, str)) or hasattr(object, "__contains__"):
            contains = value in object

        if state.verbosity >= NodeVerbosity.NORMAL:
            log.debug("Contains check", object=object, value=value, contains=contains)

        self.set_output_values({"contains": contains})


@register("data/DictGet")
class DictGet(Node):
    """
    Retrieves a value from a dictionary

    Inputs:

    - dict: Dictionary
    - key: Key

    Properties:

    - key: Key

    Outputs:

    - value: Value

    """

    class Fields:
        key = PropertyField(
            name="key",
            description="Key",
            type="str",
            default=UNRESOLVED,
        )

    def __init__(self, title="Dict Get", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("dict", socket_type="dict")
        self.add_input("key", socket_type="str")
        self.add_output("value", socket_type="any")
        self.add_output("key", socket_type="str")

        self.set_property("key", UNRESOLVED)

    async def run(self, state: GraphState):
        data = self.get_input_value("dict")
        key = self.get_input_value("key")

        value = data.get(key)

        self.set_output_values({"value": value, "key": key})


@register("data/DictPop")
class DictPop(Node):
    """
    Pops a value from a dictionary

    Inputs:

    - dict: Dictionary
    - key: Key

    Properties:

    - key: Key

    Outputs:

    - dict: Dictionary
    - value: Value
    - key: Key
    """

    class Fields:
        key = PropertyField(
            name="key",
            description="Key",
            type="str",
            default=UNRESOLVED,
        )

    def __init__(self, title="Dict Pop", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("dict", socket_type="dict")
        self.add_input("key", socket_type="str")
        self.add_output("dict", socket_type="dict")
        self.add_output("value", socket_type="any")
        self.add_output("key", socket_type="str")

        self.set_property("key", UNRESOLVED)

    async def run(self, state: GraphState):
        data = self.get_input_value("dict")
        key = self.get_input_value("key")

        value = data.pop(key, None)

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug("Dict pop", key=key, value=value)

        self.set_output_values({"dict": data, "value": value, "key": key})


@register("data/DictSet")
class DictSet(Node):
    """
    Set a value in a dictionary

    Inputs:

    - dict: Dictionary - if not provided, a new dictionary will be created
    - key: Key
    - value: Value

    Properties:

    - key: Key

    Outputs:

    - dict: Dictionary
    - key: Key
    - value: Value
    """

    class Fields:
        key = PropertyField(
            name="key",
            description="Key",
            type="str",
            default=UNRESOLVED,
        )

    def __init__(self, title="Dict Set", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("dict", socket_type="dict", optional=True)
        self.add_input("key", socket_type="str", optional=True)
        self.add_input("value", socket_type="any")

        self.add_output("dict", socket_type="dict")
        self.add_output("key", socket_type="str")
        self.add_output("value", socket_type="any")

        self.set_property("key", UNRESOLVED)

    async def run(self, state: GraphState):
        data = self.get_input_value("dict")

        if not self.is_set(data):
            data = {}

        key = self.get_input_value("key")
        value = self.get_input_value("value")

        data[key] = value

        self.set_output_values({"dict": data, "key": key, "value": value})


@register("data/MakeDict")
class MakeDict(Node):
    """
    Creates a new empty dictionary

    Inputs:

    - state: Graph state

    Properties:

    - data: Data to initialize the dictionary with

    Outputs:

    - dict: Dictionary
    """

    class Fields:
        data = PropertyField(
            name="data",
            description="Data",
            type="dict",
            default={},
        )

    def __init__(self, title="Make Dict", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state", optional=True)

        self.set_property("data", {})

        self.add_output("dict", socket_type="dict")

    async def run(self, state: GraphState):
        new_dict = self.get_property("data")

        self.set_output_values({"dict": new_dict})


@register("data/Get")
class Get(Node):
    """
    Get a value from an object using getattr

    Can be used on dictionaries as well.

    Inputs:

    - object: Object
    - attribute: Attribute

    Properties:

    - attribute: Attribute

    Outputs:

    - value: Value
    - attribute: Attribute
    - object: Object
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#44552f",
            icon="F0552",  # upload
            auto_title="GET obj.{attribute}",
        )

    class Fields:
        attribute = PropertyField(
            name="attribute",
            description="Attribute",
            type="str",
            default=UNRESOLVED,
        )

    def __init__(self, title="Get", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("object", socket_type="any")
        self.add_input("attribute", socket_type="str")

        self.set_property("attribute", UNRESOLVED)

        self.add_output("value", socket_type="any")
        self.add_output("attribute", socket_type="str")
        self.add_output("object", socket_type="any")

    async def run(self, state: GraphState):
        obj = self.get_input_value("object")
        attribute = self.get_input_value("attribute")

        if isinstance(obj, dict):
            value = obj.get(attribute)
        elif isinstance(obj, list):
            try:
                index = int(attribute)
            except (ValueError, TypeError):
                raise InputValueError(
                    self,
                    "attribute",
                    "Attribute must be an integer if object is a list",
                )
            try:
                value = obj[index]
            except IndexError:
                value = UNRESOLVED
        else:
            value = getattr(obj, attribute, None)

        self.set_output_values({"value": value, "attribute": attribute, "object": obj})


@register("data/Set")
class Set(Node):
    """
    Set a value on an object using setattr

    Can be used on dictionaries as well.

    Inputs:

    - object: Object
    - attribute: Attribute
    - value: Value

    Properties:

    - attribute: Attribute

    Outputs:

    - object: Object
    - attribute: Attribute
    - value: Value
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#2e4657",
            icon="F01DA",  # upload
            auto_title="SET obj.{attribute}",
        )

    class Fields:
        attribute = PropertyField(
            name="attribute",
            description="Attribute",
            type="str",
            default=UNRESOLVED,
        )

    def __init__(self, title="Set", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("object", socket_type="any")
        self.add_input("attribute", socket_type="str")
        self.add_input("value", socket_type="any")

        self.set_property("attribute", UNRESOLVED)

        self.add_output("object", socket_type="any")
        self.add_output("attribute", socket_type="str")
        self.add_output("value", socket_type="any")

    async def run(self, state: GraphState):
        obj = self.get_input_value("object")
        attribute = self.get_input_value("attribute")
        value = self.get_input_value("value")

        if isinstance(obj, dict):
            obj[attribute] = value
        elif isinstance(obj, list):
            try:
                index = int(attribute)
            except (ValueError, IndexError):
                raise InputValueError(
                    self,
                    "attribute",
                    "Attribute must be an integer if object is a list",
                )
            obj[index] = value
        else:
            setattr(obj, attribute, value)

        self.set_output_values({"object": obj, "attribute": attribute, "value": value})


@register("data/MakeList")
class MakeList(Node):
    """
    Creates a new empty list

    Inputs:

    - state: Graph state

    Outputs:

    - list: List
    """

    class Fields:
        item_type = PropertyField(
            name="item_type",
            description="Type of items in the list",
            type="str",
            default="any",
            generate_choices=lambda: TYPE_CHOICES,
        )

        items = PropertyField(
            name="items",
            description="Initial items in the list",
            type="list",
            default=[],
        )

    def __init__(self, title="Make List", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state", optional=True)
        self.add_input("item_type", socket_type="str", optional=True)

        self.set_property("item_type", "any")
        self.set_property("items", [])

        self.add_output("list", socket_type="list")

    async def run(self, state: GraphState):
        item_type = self.get_input_value("item_type")
        if item_type == UNRESOLVED:
            item_type = self.get_property("item_type")

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug("Creating new list", item_type=item_type)

        # Create a new empty list
        new_list = self.get_property("items")

        self.set_output_values({"list": new_list})


@register("data/ListAppend")
class ListAppend(Node):
    """
    Appends an item to a list

    Inputs:

    - list: List
    - item: Item

    Outputs:

    - list: List
    - item: Item
    """

    def __init__(self, title="List Append", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("list", socket_type="list", optional=True)
        self.add_input("item", socket_type="any")

        self.add_output("list", socket_type="list")
        self.add_output("item", socket_type="any")

    async def run(self, state: GraphState):
        list_obj = self.get_input_value("list")
        item = self.get_input_value("item")

        if list_obj == UNRESOLVED or list_obj is None:
            list_obj = []

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug("Appending item to list", list_length=len(list_obj), item=item)

        # list_node = self.get_input_socket("list").source.node

        # validate item type
        # if list_node.get_property("item_type")

        # Append the item to the list
        list_obj.append(item)

        self.set_output_values({"list": list_obj, "item": item})


@register("data/ListRemove")
class ListRemove(Node):
    """
    Removes an item from a list

    Inputs:

    - list: List
    - item: Item

    Outputs:

    - list: List
    - item: Item
    - removed: True if item was removed, False if not
    """

    def __init__(self, title="List Remove", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("list", socket_type="list")
        self.add_input("item", socket_type="any")

        self.add_output("list", socket_type="list")
        self.add_output("item", socket_type="any")
        self.add_output("removed", socket_type="bool")

    async def run(self, state: GraphState):
        list_obj = self.get_input_value("list")
        item = self.get_input_value("item")

        if list_obj == UNRESOLVED or list_obj is None:
            raise InputValueError(self, "list", "List must be provided")

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug("Removing item from list", list_length=len(list_obj), item=item)

        # Try to remove the item from the list
        removed = False
        try:
            list_obj.remove(item)
            removed = True
            if state.verbosity >= NodeVerbosity.VERBOSE:
                log.debug("Item removed from list", item=item)
        except ValueError:
            # Item not in list
            removed = False
            if state.verbosity >= NodeVerbosity.VERBOSE:
                log.debug("Item not found in list", item=item)

        self.set_output_values({"list": list_obj, "item": item, "removed": removed})


@register("data/Length")
class Length(Node):
    """
    Gets the length of an iterable

    Inputs:

    - object: Object (list, dict, etc.)

    Outputs:

    - length: Length of the object (number of items)
    """

    def __init__(self, title="Length", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("object")

        self.add_output("length", socket_type="int")

    async def run(self, state: GraphState):
        obj = self.get_input_value("object")

        # if object is generator convert to list
        if hasattr(obj, "__iter__") and not isinstance(obj, (dict, list)):
            obj = list(obj)

        self.set_output_values({"length": len(obj)})


@register("data/SelectItem")
class SelectItem(Node):
    """
    Node that takes in a list of items and selects one based on the selection function

    - random
    - cycle
    - sorted_cycle

    Inputs:

    - items: List of items
    - except: Item to exclude from selection

    Properties:

    - index: Index of item to select
    - selection_function: Selection function
    - cycle_index: Cycle index (ephemeral, read-only)

    Outputs:

    - selected_item: Selected item
    """

    class Fields:
        cycle_index = PropertyField(
            name="cycle_index",
            description="cycle index",
            type="int",
            ephemeral=True,
            default=0,
            readonly=True,
        )
        index = PropertyField(
            name="index",
            description="index",
            type="int",
            default=0,
        )
        selection_function = PropertyField(
            name="selection_function",
            description="Selection function",
            type="str",
            default="cycle",
            choices=["random", "cycle", "sorted_cycle", "direct"],
        )

    def __init__(self, title="Select Item", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("items", socket_type="list")

        self.add_input("except", socket_type="any", optional=True)

        self.add_output("selected_item", socket_type="any")

        self.set_property("index", 0)
        self.set_property("cycle_index", 0)
        self.set_property("selection_function", "cycle")

    async def run(self, state: GraphState):
        items = self.get_input_value("items")
        index = self.get_property("index")
        selection_function = self.get_property("selection_function")

        # Determine which state object to use
        state_data = state.outer.data if getattr(state, "outer", None) else state.data

        # Initialize cycle_index in state if it doesn't exist, using self.id in the key
        cycle_key = f"{self.id}_cycle_index"
        if cycle_key not in state_data:
            state_data[cycle_key] = 0

        except_items = self.get_input_value("except")

        if not isinstance(except_items, list) and except_items is not None:
            except_items = [except_items]

        items = items.copy()

        if except_items:
            items = [i for i in items if i not in except_items]

        if state_data[cycle_key] >= len(items):
            state_data[cycle_key] = 0

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug(
                "Select item",
                items=items,
                except_items=except_items,
                selection_function=selection_function,
                cycle_index=state_data[cycle_key],
            )

        if selection_function == "direct":
            try:
                selected_item = items[index]
            except IndexError:
                log.warning("Index out of range", index=index)
                selected_item = UNRESOLVED
        elif selection_function == "random":
            selected_item = random.choice(items)
        elif selection_function == "cycle":
            try:
                selected_item = items[state_data[cycle_key]]
                state_data[cycle_key] = (state_data[cycle_key] + 1) % len(items)
            except IndexError:
                log.warning("Index out of range", index=state_data[cycle_key])
                selected_item = items[0] if items else UNRESOLVED
        elif selection_function == "sorted_cycle":
            items_copy = items.copy()
            items_copy.sort()
            selected_item = items_copy[state_data[cycle_key]]
            state_data[cycle_key] = (state_data[cycle_key] + 1) % len(items)

        self.set_output_values({"selected_item": selected_item})


@register("data/DictCollector")
class DictCollector(DynamicSocketNodeBase):
    """
    Collects key-value pairs into a dictionary with dynamic inputs.
    Connect tuple outputs like (key, value) to the dynamic input slots.
    """
    
    dynamic_input_label: str = "item{i}"
    supports_dynamic_sockets: bool = True  # Frontend flag
    dynamic_input_type: str = "key/value"     # Type for dynamic sockets
    
    def __init__(self, title="Dict Collector", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        # Start with just the output - inputs added dynamically
        self.add_output("dict", socket_type="dict")
    
    async def run(self, state: GraphState):
        result_dict = {}
        
        # Process all inputs
        for socket in self.inputs:
            print("socket", socket, socket.source, socket.value)
            if socket.source and socket.value is not UNRESOLVED:
                value = socket.value
                if isinstance(value, tuple) and len(value) == 2:
                    key, val = value
                    result_dict[key] = val
        
        self.set_output_values({"dict": result_dict})


@register("data/MakeKeyValuePair")
class MakeKeyValuePair(Node):
    """
    Creates a key-value pair tuple from separate key and value inputs.
    Outputs a tuple (key, value) that can be connected to DictCollector.
    """
    
    class Fields:
        key = PropertyField(
            name="key",
            description="Key",
            type="str",
            default="",
        )
        
        value = PropertyField(
            name="value",
            description="Value",
            type="any",
            default="",
        )

    def __init__(self, title="Make Key-Value Pair", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("key", socket_type="str", optional=True)
        self.add_input("value", socket_type="any", optional=True)
        
        self.set_property("key", "")
        self.set_property("value", "")
        
        self.add_output("kv", socket_type="key/value")
    
    async def run(self, state: GraphState):
        key = self.get_input_value("key")
        value = self.get_input_value("value")
        
        # Create tuple from key and value
        result_tuple = (key, value)
        
        self.set_output_values({"kv": result_tuple})
