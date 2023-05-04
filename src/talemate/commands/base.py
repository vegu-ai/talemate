"""
Talemate Command Base class
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from talemate.emit import Emitter, emit

if TYPE_CHECKING:
    from talemate.tale_mate import CommandManager, Scene


class TalemateCommand(Emitter, ABC):
    name: str
    description: str
    aliases: list = None
    scene: Scene = None
    manager: CommandManager = None
    label: str = None

    def __init__(
        self,
        manager,
        *args,
    ):
        self.scene = manager.scene
        self.manager = manager
        self.args = args
        self.setup_emitter(self.scene)

    @classmethod
    def is_command(cls, name):
        return name == cls.name or name in cls.aliases

    @abstractmethod
    def run(self):
        raise NotImplementedError(
            "TalemateCommand.run() must be implemented by subclass"
        )
        
    @property
    def verbose_name(self):
        if self.label:
            return self.label.title()
        return self.name.replace("_", " ").title()

    def command_start(self):
        emit("command_status", self.verbose_name, status="started")
        
    def command_end(self):
        emit("command_status", self.verbose_name, status="ended")