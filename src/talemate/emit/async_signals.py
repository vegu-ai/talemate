handlers = {
}

class AsyncSignal:
    
    def __init__(self, name):
        self.receivers = []
        self.name = name
    
    def connect(self, handler):
        if handler in self.receivers:
            return
        self.receivers.append(handler)
        
    def disconnect(self, handler):
        self.receivers.remove(handler)
        
    async def send(self, emission):
        for receiver in self.receivers:
            await receiver(emission)


def _register(name:str):
    
    """
    Registers a signal handler
    
    Arguments:
        name (str): The name of the signal
        handler (signal): The signal handler
    """
    
    if name in handlers:
        raise ValueError(f"Signal {name} already registered")
    
    handlers[name] = AsyncSignal(name)
    return handlers[name]
    
def register(*names):
    """
    Registers many signal handlers
    
    Arguments:
        *names (str): The names of the signals
    """
    for name in names:
        _register(name)
        
        
def get(name:str):
    """
    Gets a signal handler
    
    Arguments:
        name (str): The name of the signal handler
    """
    return handlers.get(name)