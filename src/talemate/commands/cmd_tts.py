from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.instance import get_agent

__all__ = [
    "CmdTestTTS",
]


@register
class CmdTestTTS(TalemateCommand):
    """
    Command class for the 'test_tts' command
    """

    name = "test_tts"
    description = "Test the TTS agent"
    aliases = []

    async def run(self):
        tts_agent = get_agent("tts")

        try:
            last_message = str(self.scene.history[-1])
        except IndexError:
            last_message = "Welcome to talemate!"

        await tts_agent.generate(last_message)
