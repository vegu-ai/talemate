"""The configured decision-model slot.

Nothing here makes a request: the reported state is what the configuration says
plus what the last request a feature asked for recorded.
"""

from talemate.config import get_config
from talemate.emit import emit

from . import decision_service
from .provider import FailureCode, ProviderCapabilities
from .providers import OpenRouterDecisionProvider, SystemOneDecisionProvider
from .service import DecisionService


class DecisionModelSlot:
    def __init__(self, service: DecisionService):
        self.service = service
        self.last_failure: dict | None = None
        service.log.subscribe(self.on_request_record)

    def on_request_record(self, event: dict):
        if event["event"] != "request":
            return
        entry = event["entry"]
        if entry["status"] == "completed":
            self.last_failure = None
        elif entry["status"] == "failed":
            if entry["failure"]["code"] == FailureCode.DISABLED:
                # the slot being off is its state, not an error it made
                return
            self.last_failure = {
                "code": str(entry["failure"]["code"]),
                "dispatched": entry["dispatched"],
                "timestamp": entry["timestamp"],
            }
        else:
            return
        emit_decision_model_status()

    def apply(self):
        settings = get_config().decision_model
        # a recorded failure describes the configuration that produced it, so a
        # change of that configuration retires it rather than reporting it
        # beside the new state
        self.last_failure = None
        capabilities = ProviderCapabilities(
            max_input_tokens=settings.max_input_tokens or None,
            max_question_input_tokens=settings.max_question_input_tokens or None,
            input_token_multiplier=settings.input_token_multiplier,
        )
        if settings.provider == "systemone":
            self.service.provider = SystemOneDecisionProvider(
                settings.model,
                settings.base_url,
                lambda: get_config().decision_model.api_key,
                capabilities=capabilities,
            )
        else:
            self.service.provider = OpenRouterDecisionProvider(
                settings.model,
                lambda: get_config().openrouter.api_key,
                capabilities=capabilities,
            )
        self.service.enabled = settings.enabled
        self.service.timeout_seconds = settings.timeout_seconds

    def status(self) -> dict:
        # read from the running service rather than the stored configuration:
        # a save whose apply failed leaves the two apart, and what a feature
        # would reach is the running one
        provider = self.service.provider
        enabled = self.service.enabled
        missing = provider.missing_settings if provider else ["model"]
        return {
            "enabled": enabled,
            "provider": provider.name if provider else None,
            "model": provider.model if provider else "",
            "timeout_seconds": self.service.timeout_seconds,
            "state": "disabled"
            if not enabled
            else ("incomplete" if missing else "ready"),
            "missing": missing,
            "last_failure": self.last_failure,
        }


decision_model_slot = DecisionModelSlot(decision_service)


def configure_decision_service():
    decision_model_slot.apply()
    emit_decision_model_status()


def decision_model_status() -> dict:
    return decision_model_slot.status()


def emit_decision_model_status():
    emit("decision_model_status", data=decision_model_status())
