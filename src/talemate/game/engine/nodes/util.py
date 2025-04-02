from .core import (
    Node,
    register,
    GraphState,
    UNRESOLVED,
    InputValueError,
    PropertyField,
)

@register("util/Counter")
class Counter(Node):
    """
    Counter node that increments a numeric value inside a 
    dict and returns the new value.
    
    Inputs:
    - state: The graph state
    - dict: The dict containing the value to increment
    - key: The key to the value to increment
    - reset: If true, the value will be reset to 0
    
    Properties:
    - increment: The amount to increment the value by
    - key: The key to the value to increment
    - reset: If true, the value will be reset to 0
    
    Outputs:
    - value: The new value
    - dict: The dict with the new value
    """
    
    class Fields:
        increment = PropertyField(
            name="increment",
            type="number",
            default=1,
            step=1,
            min=1,
            description="The amount to increment the value by"
        )
        
        key = PropertyField(
            name="key",
            type="str",
            default="counter",
            description="The key to the value to increment"
        )
        
        reset = PropertyField(
            name="reset",
            type="bool",
            default=False,
            description="If true, the value will be reset to 0"
        )
    
    def __init__(self, title="Counter", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("state")
        self.add_input("dict", socket_type="dict")
        self.add_input("key", socket_type="str", optional=True)
        self.add_input("reset", socket_type="bool", optional=True)
        
        self.set_property("increment", 1)
        self.set_property("key", "counter")
        self.set_property("reset", False)
        
        self.add_output("value")
        self.add_output("dict", socket_type="dict")
        
    async def run(self, state: GraphState):
        dict_ = self.get_input_value("dict")
        key = self.get_input_value("key")
        reset = self.get_input_value("reset")
        increment = self.get_property("increment")
        
        if increment is UNRESOLVED:
            raise InputValueError(self, "increment", "Increment value is required")
        
        if reset:
            dict_[key] = 0
        else:
            dict_[key] = dict_.get(key, 0) + increment
            
        self.set_output_values({
            "value": dict_[key],
            "dict": dict_
        })
    