__all__ = ["AGENT_CLASSES", "register", "get_agent_class"]

AGENT_CLASSES = {}


class register:
    def __init__(self, condition=None):
        self.condition = condition

    def __call__(self, agent_class):
        condition = self.condition

        if condition and not condition():
            return agent_class

        typ = agent_class.agent_type

        AGENT_CLASSES[typ] = agent_class
        return agent_class


def get_agent_class(name):
    return AGENT_CLASSES.get(name)
