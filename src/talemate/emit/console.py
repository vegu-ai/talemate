from talemate.util import colored_text, wrap_text

from .base import Emission, Receiver, emit

__all__ = [
    "Console",
]


class Console(Receiver):
    COLORS = {
        "system": "yellow",
        "narrator": "light_black",
        "character": "white",
        "player": "white",
    }

    def handle_system(self, emission: Emission):
        print()
        print(
            wrap_text(
                "System: " + colored_text(emission.message, self.COLORS["system"]),
                "System",
                self.COLORS["system"],
            )
        )
        print()

    def handle_narrator(self, emission: Emission):
        print()
        print(
            wrap_text(
                "Narrator: " + colored_text(emission.message, self.COLORS["narrator"]),
                "Narrator",
                self.COLORS["narrator"],
            )
        )
        print()

    def handle_character(self, emission: Emission):
        character = emission.character
        wrapped_text = wrap_text(emission.message, character.name, character.color)
        print(" ")
        print(wrapped_text)
        print(" ")

    def handle_request_input(self, emission: Emission):
        value = input(emission.message)
        emit(
            typ="receive_input",
            message=value,
            character=emission.character,
            scene=emission.scene,
        )
