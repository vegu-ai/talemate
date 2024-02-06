
__all__ = [
    'HANDLERS',
    'register',
]

HANDLERS = {

}

class register:
    
    def __init__(self, backend_name:str, label:str):
        self.backend_name = backend_name
        self.label = label
        
    def __call__(self, mixin_cls):
        HANDLERS[self.backend_name] = {
            "label": self.label,
            "cls": mixin_cls
        }
        return mixin_cls