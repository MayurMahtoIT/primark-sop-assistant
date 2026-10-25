"""RAG orchestration: input guardrail -> condense -> embed -> hybrid search -> generate -> output guardrail."""

import logging
import re
import time
import uuid
from dataclasses import dataclass

from app.api.schemas import ChatRequest, ChatResponse, GuardrailInfo, Source
from app.auth import User
from app.config import Settings
from app.rag.embeddings import Embedder
from app.rag.guardrails import GuardrailResult
from app.rag.llm import LLM
from app.rag.prompts import (
    CONDENSE_SYSTEM_PROMPT,
    NO_ANSWER_TOKEN,
    SYSTEM_PROMPT,
    build_condense_prompt,
    build_user_prompt,
)
from app.rag.retrieval import Chunk, PostgresRetriever
from app.rag.sessions import SessionStore

logger = logging.getLogger(__name__)

MSG_NOT_FOUND = (
    "I couldn't find this in the current SOPs. Please check with the responsible DBA or SOP owner."
)
MSG_BLOCKED_INPUT = "I can only help with questions covered by the available database and operational SOPs. For anything else, contact the responsible support team."
MSG_BLOCKED_OUTPUT = "I couldn't give a reliable answer to that. Please check the approved SOP directly or contact the responsible DBA."
_CITATION_RE = re.compile(r"\[(\d+)\]")


@dataclass
class RagService:
    settings: Settings
    embedder: Embedder
    retriever: PostgresRetriever
    llm: LLM
    guardrail: object  # BedrockGuardrail | NullGuardrail
    sessions: SessionStore

    # ------------------------------------------------------------------ public
    def answer(self, req: ChatRequest, user: User) -> ChatResponse:
        started = time.perf_counter()
        session_id = req.session_id or uuid.uuid4().hex
        message_id = uuid.uuid4().hex

        gin: GuardrailResult = self.guardrail.check_input(req.question)
        if not gin.allowed:
            logger.warning("input_blocked", extra={"ctx": {"reasons": gin.reasons, "user": user.id}})
            return self._response(
                started, message_id, session_id, MSG_BLOCKED_INPUT, [], gin.status, "skipped"
            )

        question = gin.text
        history = self._clean_history(
            self.sessions.get_history(user.id, session_id, self.settings.history_turns)
        )
        standalone = self._condense(question, history)

        vector = self.embedder.embed(standalone)
        chunks = self.retriever.search(
            query=standalone,
            vector=vector,
            department=req.department,
            country=user.country,
            top_k=self.settings.retrieval_top_k,
        )
        if not chunks:
            return self._finish(
                started, message_id, session_id, user, question, MSG_NOT_FOUND, [], gin.status, "skipped"
            )

        prompt = build_user_prompt(question, chunks)
        raw, usage = self.llm.generate(SYSTEM_PROMPT, [*history, {"role": "user", "content": prompt}])

        if raw.startswith(NO_ANSWER_TOKEN):
            text = raw[len(NO_ANSWER_TOKEN) :].strip() or MSG_NOT_FOUND
            return self._finish(
                started, message_id, session_id, user, question, text, [], gin.status, "skipped"
            )

        context = "\n\n".join(c.text for c in chunks)
        gout = self.guardrail.check_output(raw, standalone, context)
        if not gout.allowed:
            logger.warning("output_blocked", extra={"ctx": {"reasons": gout.reasons, "user": user.id}})
            return self._response(
                started, message_id, session_id, MSG_BLOCKED_OUTPUT, [], gin.status, "blocked"
            )

        answer = gout.text
        cited = {int(n) for n in _CITATION_RE.findall(answer)}
        if not cited:
            logger.warning("uncited_answer", extra={"ctx": {"message_id": message_id}})
        sources = self._sources(chunks, cited)
        logger.info(
            "chat_completed",
            extra={
                "ctx": {
                    "message_id": message_id,
                    "user": user.id,
                    "department": req.department,
                    "chunks": [c.chunk_id for c in chunks],
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
            },
        )
        return self._finish(
            started, message_id, session_id, user, question, answer, sources, gin.status, gout.status
        )

    # ----------------------------------------------------------------- helpers
    def _condense(self, question: str, history: list[dict[str, str]]) -> str:
        if not history:
            return question
        text, _ = self.llm.generate(
            CONDENSE_SYSTEM_PROMPT,
            [{"role": "user", "content": build_condense_prompt(question, history)}],
            model_id=self.settings.rewrite_model_id,
            max_tokens=120,
        )
        return text.strip() or question

    @staticmethod
    def _clean_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
        while history and history[0]["role"] != "user":  # Converse requires user-first alternation
            history = history[1:]
        return history

    @staticmethod
    def _sources(chunks: list[Chunk], cited: set[int]) -> list[Source]:
        return [
            Source(
                ref=i,
                sop_id=c.sop_id,
                title=c.title,
                section=c.section,
                version=c.version,
                department=c.department,
                page=c.page,
                snippet=c.text[:240],
                score=round(c.score, 4),
                cited=i in cited,
            )
            for i, c in enumerate(chunks, start=1)
        ]

    def _finish(
        self, started, message_id, session_id, user, question, answer, sources, gin, gout
    ) -> ChatResponse:
        self.sessions.append_turn(user.id, session_id, message_id, question, answer)
        return self._response(started, message_id, session_id, answer, sources, gin, gout)

    @staticmethod
    def _response(started, message_id, session_id, answer, sources, gin, gout) -> ChatResponse:
        return ChatResponse(
            message_id=message_id,
            session_id=session_id,
            answer=answer,
            sources=sources,
            guardrails=GuardrailInfo(input=gin, output=gout),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
