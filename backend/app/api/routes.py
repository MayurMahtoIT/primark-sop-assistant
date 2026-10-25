import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.schemas import ChatRequest, ChatResponse, FeedbackRequest
from app.auth import User, get_current_user
from app.rag.guardrails import GuardrailUnavailable

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    """Liveness - used by the ALB and the container HEALTHCHECK. Must not touch dependencies."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def readyz(request: Request, response: Response) -> dict:
    """Readiness - verifies the vector store is reachable."""
    try:
        ok = request.app.state.retriever.ping()
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"vector_store": "up" if ok else "down"}


@router.post("/v1/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, user: User = Depends(get_current_user)) -> ChatResponse:
    try:
        return request.app.state.rag.answer(req, user)
    except GuardrailUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The safety service is temporarily unavailable. Please try again shortly.",
        ) from exc


@router.post("/v1/feedback", status_code=status.HTTP_204_NO_CONTENT)
def feedback(req: FeedbackRequest, request: Request, user: User = Depends(get_current_user)) -> Response:
    request.app.state.sessions.add_feedback(user.id, req.session_id, req.message_id, req.rating, req.comment)
    logger.info(
        "feedback",
        extra={"ctx": {"message_id": req.message_id, "rating": req.rating, "has_comment": bool(req.comment)}},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
