"""Abstract LLM provider.

A provider only needs to implement `_complete(system, user)` returning raw text.
The base class adds JSON-mode convenience (`generate_json`) shared by all
providers, including parsing tolerant of code fences and surrounding prose.
"""

from __future__ import annotations

import abc

from app.config import Settings
from app.logging_config import get_logger
from app.utils import extract_json

log = get_logger(__name__)


class LLMError(RuntimeError):
    """Raised when the provider cannot produce a usable response."""


class LLMProviderBase(abc.ABC):
    """Common interface for all text LLMs used by the pipeline."""

    #: Human-readable provider name for logs.
    name: str = "llm"

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    # --------------------------- to implement ---------------------------- #
    @abc.abstractmethod
    def _complete(self, system: str, user: str, *, json_mode: bool) -> str:
        """Return the raw text completion for a system+user prompt."""

    # ----------------------------- shared -------------------------------- #
    def generate_text(self, system: str, user: str) -> str:
        text = self._complete(system, user, json_mode=False)
        log.debug("llm_text", provider=self.name, chars=len(text))
        return text

    def generate_json(self, system: str, user: str) -> dict | list:
        """Generate and parse a JSON object/array, retrying once on parse error.

        Many providers honour a JSON response mode; even when they don't, the
        prompts ask for strict JSON and `extract_json` tolerates stray prose.
        """
        raw = self._complete(system, user, json_mode=True)
        try:
            return extract_json(raw)
        except ValueError:
            log.warning("llm_json_reparse", provider=self.name)
            fix = (
                "Your previous reply could not be parsed as JSON. Reply again "
                "with ONLY the valid JSON value, no prose, no code fences."
            )
            raw = self._complete(system, f"{user}\n\n{fix}\n\nPREVIOUS:\n{raw}", json_mode=True)
            return extract_json(raw)
