"""Amazon Bedrock Guardrails integration (ApplyGuardrail API).

Input  : prompt-attack, denied topics, content filters, PII masking.
Output : content filters, PII masking, plus contextual-grounding (answer must be supported by the SOP excerpts).
Fail-closed: if the guardrail service is unreachable the request is rejected, never passed through.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

MAX_GROUNDING_CHARS = 60_000


class GuardrailUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    text: str
    status: str  # passed | anonymized | blocked
    reasons: tuple[str, ...] = ()


def blocked_reasons(assessments: list[dict] | None) -> list[str]:
    """Flatten ApplyGuardrail assessments into the list of policies that *blocked* the content."""
    reasons: list[str] = []
    for a in assessments or []:
        for t in a.get("topicPolicy", {}).get("topics", []):
            if t.get("action") == "BLOCKED":
                reasons.append(f"topic:{t.get('name')}")
        for f in a.get("contentPolicy", {}).get("filters", []):
            if f.get("action") == "BLOCKED":
                reasons.append(f"content:{f.get('type')}")
        wp = a.get("wordPolicy", {})
        for w in [*wp.get("customWords", []), *wp.get("managedWordLists", [])]:
            if w.get("action") == "BLOCKED":
                reasons.append("word")
        sp = a.get("sensitiveInformationPolicy", {})
        for p in [*sp.get("piiEntities", []), *sp.get("regexes", [])]:
            if p.get("action") == "BLOCKED":
                reasons.append(f"pii:{p.get('type') or p.get('name')}")
        for f in a.get("contextualGroundingPolicy", {}).get("filters", []):
            if f.get("action") == "BLOCKED":
                reasons.append(f"grounding:{f.get('type')}")
    return reasons


class NullGuardrail:
    """Local-development stand-in. Config validation forbids this outside ENV=local."""

    def check_input(self, text: str) -> GuardrailResult:
        return GuardrailResult(True, text, "passed")

    def check_output(self, answer: str, query: str, grounding_source: str) -> GuardrailResult:
        return GuardrailResult(True, answer, "passed")


class BedrockGuardrail:
    def __init__(self, client, guardrail_id: str, version: str):
        self._client = client
        self._id = guardrail_id
        self._version = version
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="guardrail")

    def _apply(self, source: str, content: list[dict]) -> dict:
        try:
            return self._client.apply_guardrail(
                guardrailIdentifier=self._id,
                guardrailVersion=self._version,
                source=source,
                content=content,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error("guardrail_unavailable", extra={"ctx": {"error": str(exc)}})
            raise GuardrailUnavailable(str(exc)) from exc

    @staticmethod
    def _evaluate(resp: dict, original: str) -> GuardrailResult:
        if resp.get("action") != "GUARDRAIL_INTERVENED":
            return GuardrailResult(True, original, "passed")
        reasons = blocked_reasons(resp.get("assessments"))
        replacement = "".join(o.get("text", "") for o in resp.get("outputs", []))
        if reasons:
            return GuardrailResult(False, replacement, "blocked", tuple(reasons))
        return GuardrailResult(True, replacement or original, "anonymized")

    def check_input(self, text: str) -> GuardrailResult:
        resp = self._apply("INPUT", [{"text": {"text": text}}])
        return self._evaluate(resp, text)

    def check_output(self, answer: str, query: str, grounding_source: str) -> GuardrailResult:
        # Call 1: content filters + PII masking on the answer -> sanitised text.
        safety = self._pool.submit(self._apply, "OUTPUT", [{"text": {"text": answer}}])
        # Call 2: contextual grounding - is the answer supported by (and relevant to) the SOP excerpts?
        grounding = self._pool.submit(
            self._apply,
            "OUTPUT",
            [
                {
                    "text": {
                        "text": grounding_source[:MAX_GROUNDING_CHARS],
                        "qualifiers": ["grounding_source"],
                    }
                },
                {"text": {"text": query, "qualifiers": ["query"]}},
                {"text": {"text": answer, "qualifiers": ["guard_content"]}},
            ],
        )
        safety_result = self._evaluate(safety.result(), answer)
        grounding_resp = grounding.result()
        grounding_reasons = blocked_reasons(grounding_resp.get("assessments"))

        if not safety_result.allowed:
            return safety_result
        if grounding_reasons:
            return GuardrailResult(False, "", "blocked", tuple(grounding_reasons))
        return safety_result
