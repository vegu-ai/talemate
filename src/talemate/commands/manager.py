import structlog
import json

from talemate.emit import AbortCommand, Emitter

log = structlog.get_logger("talemate.commands.manager")


class Manager(Emitter):
    """
    TaleMateCommand class to handle user command
    """

    command_classes = []

    @classmethod
    def register(cls, command_cls):
        cls.command_classes.append(command_cls)

    @classmethod
    def is_command(cls, message):
        return message.startswith("!")

    def __init__(self, scene):
        self.scene = scene
        self.aliases = self.build_aliases()
        self.processing_command = False
        self.setup_emitter(scene)

    def build_aliases(self):
        aliases = {}
        for name, method in Manager.__dict__.items():
            if hasattr(method, "aliases"):
                for alias in method.aliases:
                    aliases[alias] = name.replace("cmd_", "")
        return aliases

    async def execute(self, cmd):
        # commands start with ! and are followed by a command name
        cmd = cmd.strip()
        cmd_args = ""
        cmd_kwargs = {}
        if not self.is_command(cmd):
            return False

        if ":" in cmd:
            # split command name and args which are separated by a colon
            cmd_name, cmd_args = cmd[1:].split(":", 1)
            cmd_args_unsplit = cmd_args
            cmd_args = cmd_args.split(":")
            
        else:
            cmd_name = cmd[1:]
            cmd_args = []

        for command_cls in self.command_classes:
            if command_cls.is_command(cmd_name):
                
                if command_cls.argument_cls:
                    cmd_kwargs = json.loads(cmd_args_unsplit)
                    cmd_args = []
                
                command = command_cls(self, *cmd_args, **cmd_kwargs)
                try:
                    self.processing_command = True
                    command.command_start()
                    await command.run()
                    if command.sets_scene_unsaved:
                        self.scene.saved = False
                except AbortCommand:
                    log.debug("Command aborted")
                except Exception:
                    raise
                finally:
                    command.command_end()
                    self.processing_command = False
                return True

        self.system_message(f"Unknown command: {cmd_name}")

        return True


def register(command_cls):
    Manager.command_classes.append(command_cls)

    setattr(Manager, f"cmd_{command_cls.name}", command_cls.run)

    return command_cls
