"""Conversation memory + feedback. DynamoDB in AWS (with TTL), in-memory for local dev."""

import time
from collections import defaultdict
from typing import Protocol

from boto3.dynamodb.conditions import Key


class SessionStore(Protocol):
    def get_history(self, user_id: str, session_id: str, limit_turns: int) -> list[dict[str, str]]: ...
    def append_turn(
        self, user_id: str, session_id: str, message_id: str, question: str, answer: str
    ) -> None: ...
    def add_feedback(
        self, user_id: str, session_id: str, message_id: str, rating: str, comment: str | None
    ) -> None: ...


def _pk(user_id: str, session_id: str) -> str:
    # user id is part of the key: a session id alone can never read another colleague's history
    return f"USER#{user_id}#S#{session_id}"


def _to_messages(turns: list[dict]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for t in turns:
        messages.append({"role": "user", "content": t["question"]})
        messages.append({"role": "assistant", "content": t["answer"]})
    return messages


class InMemorySessionStore:
    def __init__(self) -> None:
        self._turns: dict[str, list[dict]] = defaultdict(list)
        self.feedback: list[dict] = []

    def get_history(self, user_id, session_id, limit_turns):
        return _to_messages(self._turns[_pk(user_id, session_id)][-limit_turns:])

    def append_turn(self, user_id, session_id, message_id, question, answer):
        self._turns[_pk(user_id, session_id)].append(
            {"message_id": message_id, "question": question, "answer": answer}
        )

    def add_feedback(self, user_id, session_id, message_id, rating, comment):
        self.feedback.append(
            {
                "user": user_id,
                "session": session_id,
                "message": message_id,
                "rating": rating,
                "comment": comment,
            }
        )


class DynamoSessionStore:
    def __init__(self, table, ttl_seconds: int):
        self._table = table
        self._ttl = ttl_seconds

    def get_history(self, user_id, session_id, limit_turns):
        resp = self._table.query(
            KeyConditionExpression=Key("pk").eq(_pk(user_id, session_id)) & Key("sk").begins_with("T#"),
            ScanIndexForward=False,
            Limit=limit_turns,
            ConsistentRead=True,
        )
        return _to_messages(list(reversed(resp.get("Items", []))))

    def append_turn(self, user_id, session_id, message_id, question, answer):
        now = time.time_ns()
        self._table.put_item(
            Item={
                "pk": _pk(user_id, session_id),
                "sk": f"T#{now:020d}#{message_id}",
                "message_id": message_id,
                "question": question,  # already PII-masked by the input guardrail
                "answer": answer,
                "expires_at": int(time.time()) + self._ttl,
            }
        )

    def add_feedback(self, user_id, session_id, message_id, rating, comment):
        now = time.time_ns()
        self._table.put_item(
            Item={
                "pk": _pk(user_id, session_id),
                "sk": f"F#{now:020d}#{message_id}",
                "message_id": message_id,
                "rating": rating,
                "comment": comment or "",
                "expires_at": int(time.time()) + self._ttl * 30,
            }
        )
