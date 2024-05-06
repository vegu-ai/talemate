__all__ = ["RemoteServiceMixin"]


class RemoteServiceMixin:

    def prompt_template(self, system_message: str, prompt: str):
        if "<|BOT|>" in prompt:
            _, right = prompt.split("<|BOT|>", 1)
            if right:
                prompt = prompt.replace("<|BOT|>", "\nStart your response with: ")
            else:
                prompt = prompt.replace("<|BOT|>", "")

        return prompt

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
            self.set_client(kwargs.get("max_token_length"))
        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])


    def on_config_saved(self, event):
        config = event.data
        self.config = config
        self.set_client(max_token_length=self.max_token_length)

    def tune_prompt_parameters(self, parameters: dict, kind: str):
        super().tune_prompt_parameters(parameters, kind)
        keys = list(parameters.keys())
        valid_keys = ["temperature", "max_tokens"]
        for key in keys:
            if key not in valid_keys:
                del parameters[key]

    async def status(self):
        self.emit_status()
