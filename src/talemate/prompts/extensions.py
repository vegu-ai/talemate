from jinja2 import nodes
from jinja2.ext import Extension


class CaptureContextExtension(Extension):
    """
    A Jinja2 extension that captures the rendered content within a block and makes it available
    in the prompt instance.

    Usage:
        {% capture_context %}
        Some content to capture
        {% end_capture_context %}

    The content within the block is rendered normally in the template output, but is also
    appended to the `captured_context` attribute of the `Prompt` instance. This allows
    extraction of dynamically generated content (like sub-prompts or context) from the
    rendering process.
    """

    tags = {"capture_context"}

    def parse(self, parser):
        lineno = next(parser.stream).lineno
        body = parser.parse_statements(["name:end_capture_context"], drop_needle=True)
        return nodes.CallBlock(
            self.call_method("_capture", []), [], [], body
        ).set_lineno(lineno)

    def _capture(self, caller):
        content = caller()
        prompt = self.environment.globals.get("prompt_instance")
        if prompt:
            current = getattr(prompt, "captured_context", "")
            prompt.captured_context = current + content
        return content
