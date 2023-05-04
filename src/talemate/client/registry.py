__all__ = ["CLIENT_CLASSES", "register", "get_client_class"]

CLIENT_CLASSES = {}


class register:
    def __init__(self, condition=None):
        self.condition = condition

    def __call__(self, client_class):
        condition = self.condition

        if condition and not condition():
            return client_class

        typ = client_class.client_type

        CLIENT_CLASSES[typ] = client_class
        return client_class


def get_client_class(name):
    return CLIENT_CLASSES.get(name)
