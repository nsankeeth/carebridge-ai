"""Posting messages into a thread."""

from typing import Any

from sqlalchemy.orm import Session

from app.models import MedicalCase, Message, MessageAuthor, User, utcnow


def post_message(db: Session, case: MedicalCase, author_type: MessageAuthor, body: str, payload: dict[str, Any] | None = None, author: User | None = None) -> Message:
    m = Message(case_id=case.id, author_type=author_type, author_user_id=author.id if author else None, body=body, payload=payload, created_at=utcnow())
    db.add(m)
    db.flush()
    if m not in case.messages:
        case.messages.append(m)
    return m
