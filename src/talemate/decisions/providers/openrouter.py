from .typesafe import TypeSafeDecisionProvider


DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"


class OpenRouterDecisionProvider(TypeSafeDecisionProvider):
    name = "openrouter"
    url = DECISIONS_URL
    requires_api_key = True
