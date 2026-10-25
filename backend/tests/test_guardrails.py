import pytest
from botocore.exceptions import ClientError

from app.rag.guardrails import BedrockGuardrail, GuardrailUnavailable, blocked_reasons


class FakeBedrock:
    def __init__(self, responses=None, error=False):
        self.responses = responses or []
        self.error = error
        self.calls = []

    def apply_guardrail(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "ApplyGuardrail")
        return self.responses.pop(0) if self.responses else {"action": "NONE"}


def test_pass_through():
    g = BedrockGuardrail(FakeBedrock(), "gid", "1")
    r = g.check_input("hello")
    assert r.allowed and r.status == "passed" and r.text == "hello"


def test_pii_is_anonymized_not_blocked():
    resp = {
        "action": "GUARDRAIL_INTERVENED",
        "outputs": [{"text": "call {PHONE}"}],
        "assessments": [
            {"sensitiveInformationPolicy": {"piiEntities": [{"type": "PHONE", "action": "ANONYMIZED"}]}}
        ],
    }
    r = BedrockGuardrail(FakeBedrock([resp]), "gid", "1").check_input("call 0123")
    assert r.allowed and r.status == "anonymized" and r.text == "call {PHONE}"


def test_denied_topic_blocks():
    resp = {
        "action": "GUARDRAIL_INTERVENED",
        "outputs": [{"text": "blocked"}],
        "assessments": [{"topicPolicy": {"topics": [{"name": "LEGAL_ADVICE", "action": "BLOCKED"}]}}],
    }
    r = BedrockGuardrail(FakeBedrock([resp]), "gid", "1").check_input("can I sue?")
    assert not r.allowed and r.reasons == ("topic:LEGAL_ADVICE",)


def test_output_grounding_failure_blocks_and_sends_qualifiers():
    safety = {"action": "NONE"}
    grounding = {
        "action": "GUARDRAIL_INTERVENED",
        "assessments": [
            {"contextualGroundingPolicy": {"filters": [{"type": "GROUNDING", "action": "BLOCKED"}]}}
        ],
    }
    fake = FakeBedrock()
    # thread order is not deterministic -> route by presence of qualifiers
    fake.apply_guardrail = lambda **kw: grounding if "qualifiers" in kw["content"][0]["text"] else safety
    r = BedrockGuardrail(fake, "gid", "1").check_output("answer", "q", "source")
    assert not r.allowed and r.reasons == ("grounding:GROUNDING",)


def test_fail_closed_when_service_unavailable():
    with pytest.raises(GuardrailUnavailable):
        BedrockGuardrail(FakeBedrock(error=True), "gid", "1").check_input("hi")


def test_blocked_reasons_empty_for_none():
    assert blocked_reasons(None) == []
