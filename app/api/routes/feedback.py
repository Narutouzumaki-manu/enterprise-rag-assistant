
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import FEEDBACK, record_audit
from app.api.dependencies import get_current_user, get_db
from app.db import models, repository
from app.schemas.api import FeedbackRequest, FeedbackResponse

router = APIRouter(prefix="/feedback")


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    request: Request,
    body: FeedbackRequest,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    message = await repository.get_rateable_message(db, user.id, body.message_id)
    if message is None:  # unknown, a user message, someone else's or deleted: all look the same
        raise HTTPException(status_code=404, detail="Message not found.")
    comment = body.comment.strip() if body.comment else None
    await repository.save_feedback(
        db,
        message_id=message.id,
        user_id=user.id,
        rating=body.rating,
        comment=comment or None,
    )
    await record_audit(
        request, FEEDBACK, user_id=user.id, message_id=message.id, rating=body.rating
    )
    return FeedbackResponse(message_id=message.id, rating=body.rating, comment=comment or None)
