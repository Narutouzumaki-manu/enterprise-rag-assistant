from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_app_settings, get_db
from app.core.config import Settings
from app.core.security import DUMMY_PASSWORD_HASH, create_access_token, verify_password
from app.db import repository
from app.schemas.api import LoginRequest, TokenResponse
from app.api.limits import LOGIN_LIMIT, client_ip, limiter
from app.api.audit import LOGIN_FAILED, record_audit

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenResponse)
@limiter.limit(LOGIN_LIMIT, key_func=client_ip)
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> TokenResponse:
    user = await repository.get_user_by_email(db, body.email)
    # Always check a hash, even for an unknown email, so both cases take the same time.
    hash_to_check = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_ok = await run_in_threadpool(verify_password, body.password, hash_to_check)
    if user is None or not password_ok:
        await record_audit(request, LOGIN_FAILED, client=client_ip(request))
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        expires_in=settings.jwt_expire_minutes * 60,
    )