"""Tests for Ollama client parameter cleanup."""

from talemate.client.base import STOPPING_STRINGS
from talemate.client.ollama import OllamaClient


class TestCleanPromptParameters:
    def test_stop_list_survives_cleanup(self):
        client = OllamaClient(name="oll_params")
        parameters = {
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 50,
            "stream": True,
            "stopping_strings": ["x"],
            "extra_stopping_strings": ["Bob: "],
            "stop": STOPPING_STRINGS + ["Bob: "],
            "unsupported_param": 1,
        }

        client.clean_prompt_parameters(parameters)

        assert parameters["stop"] == STOPPING_STRINGS + ["Bob: "]
        assert parameters["num_predict"] == 50
        assert "max_tokens" not in parameters
        assert "stream" not in parameters
        assert "stopping_strings" not in parameters
        assert "extra_stopping_strings" not in parameters
        assert "unsupported_param" not in parameters
