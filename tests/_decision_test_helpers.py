from talemate.decisions import ProviderCapabilities, ProviderResponse


class FakeDecisionProvider:
    name = "fake"
    model = "any-model-name"
    ready = True
    capabilities = ProviderCapabilities()

    def __init__(self):
        self.calls = []
        self.handler = None

    def serialize_question(self, question):
        return question.model_dump(exclude_none=True)

    def respond(self, request) -> ProviderResponse:
        raise NotImplementedError

    async def request(self, request):
        self.calls.append(request)
        if self.handler:
            return await self.handler(request)
        return self.respond(request)
