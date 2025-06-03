__all__ = [
    'base_node_type',
    'get_base_type',
    'BASE_TYPES',
]

BASE_TYPES = {}

def get_base_type(base_type:str):
    return BASE_TYPES.get(base_type)

class base_node_type:
    def __init__(self, base_type:str):
        self.base_type = base_type
    
    def __call__(self, cls):
        cls.base_type = self.base_type
        BASE_TYPES[self.base_type] = cls
        return cls