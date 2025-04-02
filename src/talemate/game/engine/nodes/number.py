import random
import math
import statistics
import structlog
from .core import Node, GraphState, UNRESOLVED, PropertyField, InputValueError
from .registry import register

log = structlog.get_logger("talemate.game.engine.nodes.number")

class NumberNode(Node):
    
    def require_number_input(self, name:str, types:tuple=(int, float)):
        
        value = self.require_input(name)
        
        if isinstance(value, str):
            try:
                if float in types:
                    value = float(value)
                else:
                    value = int(value)
            except ValueError:
                raise InputValueError(self, name, "Invalid number")
            
        if not isinstance(value, types):
            raise InputValueError(self, name, "Value must be a number")
        
        return value

@register("data/number/Make")
class MakeNumber(NumberNode):
    """Creates a number with a specified value
    
    Creates either an integer or floating point number with the specified value.
    
    Properties:
    
    - number_type: Type of number to create ("int" or "float")
    - value: The numeric value to create
    
    Outputs:
    
    - value: The created number value
    """
    
    class Fields:
        number_type = PropertyField(
            name="number_type",
            description="Type of number to create",
            type="str",
            default="float",
            choices=["int", "float"]
        )
        
        value = PropertyField(
            name="value",
            description="The numeric value to create",
            type="number",
            default=0
        )
    
    def setup(self):
        self.set_property("value", 0)
        self.set_property("number_type", "float")
        self.add_output("value", socket_type="any")  # Can be int or float
        
    async def run(self, state: GraphState):
        
        number_type = self.get_property("number_type")
        
        if number_type == "int":
            types = (int,)
        else:
            types = (float,)
        
        value = self.require_number_input("value", types)
        self.set_output_values({"value": value})

@register("data/number/BasicArithmetic")
class BasicArithmetic(NumberNode):
    """Performs basic arithmetic operations
    
    Performs one of the following operations on two input values: add, subtract, 
    multiply, divide, power, or modulo.
    
    Inputs:
    
    - a: First operand (number)
    - b: Second operand (number)
    
    Properties:
    
    - operation: Arithmetic operation to perform (add, subtract, multiply, divide, power, modulo)
    
    Outputs:
    
    - result: Result of the arithmetic operation
    """
    
    class Fields:
        operation = PropertyField(
            name="operation",
            description="Arithmetic operation to perform",
            type="str",
            default="add",
            choices=["add", "subtract", "multiply", "divide", "power", "modulo"]
        )
        
        a = PropertyField(
            name="a",
            description="First value to compare",
            type="number",
            default=0
        )
        b = PropertyField(
            name="b",
            description="Second value to compare",
            type="number",
            default=0
        )
    
    
    def setup(self):
        self.add_input("a", socket_type="int,float")
        self.add_input("b", socket_type="int,float")
        self.add_output("result", socket_type="int,float")
        
        self.set_property("operation", "add")
        self.set_property("a", 0)
        self.set_property("b", 0)
        
    async def run(self, state: GraphState):
        a = self.require_number_input("a")
        b = self.require_number_input("b")
        operation = self.get_property("operation")
        
        try:
            if operation == "add":
                result = a + b
            elif operation == "subtract":
                result = a - b
            elif operation == "multiply":
                result = a * b
            elif operation == "divide":
                if b == 0:
                    raise InputValueError(self, "b", "Division by zero")
                result = a / b
            elif operation == "power":
                result = a ** b
            elif operation == "modulo":
                if b == 0:
                    raise InputValueError(self, "b", "Modulo by zero")
                result = a % b
                
            self.set_output_values({"result": result})
            
        except Exception as e:
            raise InputValueError(self, "a", f"Calculation error: {str(e)}")

@register("data/number/Compare")
class Compare(NumberNode):
    """Compares two numbers
    
    Performs comparison operations between two numeric values with optional tolerance
    for floating point comparisons.
    
    Inputs:
    
    - a: First value to compare (number)
    - b: Second value to compare (number)
    
    Properties:
    
    - operation: Comparison operation to perform (equals, not_equals, greater_than, less_than, greater_equal, less_equal)
    - tolerance: Tolerance for floating point equality comparison
    
    Outputs:
    
    - result: Boolean result of the comparison
    """
    
    class Fields:
        operation = PropertyField(
            name="operation",
            description="Comparison operation to perform",
            type="str",
            default="equals",
            choices=["equals", "not_equals", "greater_than", "less_than", 
                    "greater_equal", "less_equal"]
        )
        tolerance = PropertyField(
            name="tolerance",
            description="Tolerance for floating point comparison",
            type="float",
            default=0.0001
        )
        a = PropertyField(
            name="a",
            description="First value to compare",
            type="number",
            default=0
        )
        b = PropertyField(
            name="b",
            description="Second value to compare",
            type="number",
            default=0
        )
    
    def setup(self):
        self.add_input("a", socket_type="int,float")
        self.add_input("b", socket_type="int,float")
        self.add_output("result", socket_type="bool")
        
        self.set_property("operation", "equals")
        self.set_property("tolerance", 0.0001)  # For floating point comparison
        self.set_property("a", 0)
        self.set_property("b", 0)
        
    async def run(self, state: GraphState):
        a = self.require_number_input("a")
        b = self.require_number_input("b")
        operation = self.get_property("operation")
        tolerance = self.get_property("tolerance")
        
        if operation == "equals":
            result = abs(a - b) <= tolerance
        elif operation == "not_equals":
            result = abs(a - b) > tolerance
        elif operation == "greater_than":
            result = a > b
        elif operation == "less_than":
            result = a < b
        elif operation == "greater_equal":
            result = a >= b
        elif operation == "less_equal":
            result = a <= b
            
        self.set_output_values({"result": result})


@register("data/number/MinMax")
class MinMax(NumberNode):
    """Finds minimum or maximum in a list of numbers
    
    Takes a list of numbers and finds either the minimum or maximum value,
    returning both the value and its index in the list.
    
    Inputs:
    
    - numbers: List of numbers to analyze
    
    Properties:
    
    - operation: Operation to perform (min or max)
    
    Outputs:
    
    - result: The minimum or maximum value
    - index: The index position of the minimum or maximum value in the list
    """
    
    class Fields:
        operation = PropertyField(
            name="operation",
            description="Operation to perform",
            type="str",
            default="min",
            choices=["min", "max"]
        )
    
    def setup(self):
        self.add_input("numbers", socket_type="list")
        self.add_output("result", socket_type="int,float")
        self.add_output("index", socket_type="int")
        
        self.set_property("operation", "min")
        
    async def run(self, state: GraphState):
        numbers = self.get_input_value("numbers")
        operation = self.get_property("operation")
        
        if not numbers:
            raise InputValueError(self, "numbers", "Empty list provided")
            
        if not all(isinstance(n, (int, float)) for n in numbers):
            raise InputValueError(self, "numbers", "All items must be numbers")
            
        if operation == "min":
            result = min(numbers)
            index = numbers.index(result)
        elif operation == "max":
            result = max(numbers)
            index = numbers.index(result)
            
        self.set_output_values({
            "result": result,
            "index": index
        })

@register("data/number/Sum")
class Sum(NumberNode):
    """Sums a list of numbers
    
    Calculates the sum of all values in a list of numbers.
    
    Inputs:
    
    - numbers: List of numbers to sum
    
    Outputs:
    
    - result: The sum of all numbers in the list
    """
    
    def setup(self):
        self.add_input("numbers", socket_type="list")
        self.add_output("result", socket_type="int,float")
        
        self.set_property("numbers", [])
        
    async def run(self, state: GraphState):
        numbers = self.get_input_value("numbers")
        
        if not all(isinstance(n, (int, float)) for n in numbers):
            raise InputValueError(self, "numbers", "All items must be numbers")
            
        result = sum(numbers)
        self.set_output_values({"result": result})

@register("data/number/Average")
class Average(NumberNode):
    """Calculates average of a list of numbers
    
    Calculates one of three types of average (mean, median, or mode)
    from a list of numeric values.
    
    Inputs:
    
    - numbers: List of numbers to calculate average from
    
    Properties:
    
    - method: Type of average to calculate (mean, median, mode)
    
    Outputs:
    
    - result: The calculated average value
    """
    
    class Fields:
        method = PropertyField(
            name="method",
            description="Type of average to calculate",
            type="str",
            default="mean",
            choices=["mean", "median", "mode"]
        )
    
    def setup(self):
        self.add_input("numbers", socket_type="list")
        self.add_output("result", socket_type="int,float")
        
        self.set_property("method", "mean")
        
    async def run(self, state: GraphState):
        numbers = self.get_input_value("numbers")
        method = self.get_property("method")
        
        if not numbers:
            raise InputValueError(self, "numbers", "Empty list provided")
            
        if not all(isinstance(n, (int, float)) for n in numbers):
            raise InputValueError(self, "numbers", "All items must be numbers")
            
        try:
            if method == "mean":
                result = statistics.mean(numbers)
            elif method == "median":
                result = statistics.median(numbers)
            elif method == "mode":
                try:
                    result = statistics.mode(numbers)
                except statistics.StatisticsError:
                    # Handle multimodal or no mode case
                    result = None
                    
            self.set_output_values({"result": result})
            
        except Exception as e:
            raise InputValueError(self, "numbers", f"Calculation error: {str(e)}")

@register("data/number/Random")
class Random(NumberNode):
    """Generates random numbers
    
    Generates random numbers using various distributions (uniform, integer, normal)
    or selects a random item from a list of choices.
    
    Inputs:
    
    - min: Minimum value for uniform/integer distribution (optional)
    - max: Maximum value for uniform/integer distribution (optional)
    - mean: Mean value for normal distribution (optional)
    - std_dev: Standard deviation for normal distribution (optional)
    - choices: List to select a random item from (optional)
    
    Properties:
    
    - method: Type of random number to generate (uniform, integer, normal, choice)
    - min: Default minimum value
    - max: Default maximum value
    - mean: Default mean value
    - std_dev: Default standard deviation value
    
    Outputs:
    
    - result: The generated random number or selected item
    """
    
    class Fields:
        method = PropertyField(
            name="method",
            description="Type of random number to generate",
            type="str",
            default="uniform",
            choices=["uniform", "integer", "normal", "choice"]
        )
        min = PropertyField(
            name="min",
            description="Minimum value for uniform/integer distribution",
            type="float",
            default=0.0
        )
        max = PropertyField(
            name="max",
            description="Maximum value for uniform/integer distribution",
            type="float",
            default=1.0
        )
        mean = PropertyField(
            name="mean",
            description="Mean value for normal distribution",
            type="float",
            default=0.0
        )
        std_dev = PropertyField(
            name="std_dev",
            description="Standard deviation for normal distribution",
            type="float",
            default=1.0
        )
    
    def setup(self):
        self.add_input("min", socket_type="int,float", optional=True)
        self.add_input("max", socket_type="int,float", optional=True)
        self.add_input("mean", socket_type="int,float", optional=True)
        self.add_input("std_dev", socket_type="int,float", optional=True)
        self.add_input("choices", socket_type="list", optional=True)
        
        self.add_output("result", socket_type="int,float")
        
        self.set_property("method", "uniform")
        self.set_property("min", 0.0)
        self.set_property("max", 1.0)
        self.set_property("mean", 0.0)
        self.set_property("std_dev", 1.0)
        
    async def run(self, state: GraphState):
        method = self.get_property("method")
        
        if method == "uniform":
            min_val = self.require_number_input("min")
            max_val = self.require_number_input("max")
            result = random.uniform(min_val, max_val)
            
        elif method == "integer":
            min_val = int(self.require_number_input("min"))
            max_val = int(self.require_number_input("max"))
            result = random.randint(min_val, max_val)
            
        elif method == "normal":
            mean = self.require_number_input("mean")
            std_dev = self.require_number_input("std_dev")
            
            if std_dev <= 0:
                raise InputValueError(self, "std_dev", "Standard deviation must be positive")
                
            result = random.normalvariate(mean, std_dev)
            
        elif method == "choice":
            choices = self.get_input_value("choices")
            
            if not choices:
                raise InputValueError(self, "choices", "Empty list provided")
                
            result = random.choice(choices)
            
        self.set_output_values({"result": result})

@register("data/number/Clamp")
class Clamp(NumberNode):
    """Constrains a number within a specified range
    
    Takes a value and ensures it falls within a specific minimum and maximum range.
    If the value is below the minimum, it returns the minimum. If it's above the
    maximum, it returns the maximum.
    
    Inputs:
    
    - value: The number to constrain
    - min: Minimum allowed value
    - max: Maximum allowed value
    
    Outputs:
    
    - result: The value constrained to the specified range
    """
    
    class Fields:
        value = PropertyField(
            name="value",
            description="The number to constrain",
            type="number",
            default=0
        )
        min = PropertyField(
            name="min",
            description="Minimum allowed value",
            type="number",
            default=0
        )
        max = PropertyField(
            name="max",
            description="Maximum allowed value",
            type="number",
            default=1
        )
    
    def setup(self):
        self.add_input("value", socket_type="int,float")
        self.add_input("min", socket_type="int,float")
        self.add_input("max", socket_type="int,float")
        self.add_output("result", socket_type="int,float")
        
        self.set_property("value", 0)
        self.set_property("min", 0)
        self.set_property("max", 1)
        
    async def run(self, state: GraphState):
        value = self.require_number_input("value")
        min_val = self.require_number_input("min")
        max_val = self.require_number_input("max")
        
        if min_val > max_val:
            raise InputValueError(self, "min", "Minimum value cannot be greater than maximum")
            
        result = max(min_val, min(value, max_val))
        self.set_output_values({"result": result})