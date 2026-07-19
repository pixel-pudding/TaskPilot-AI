from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from core.auth import (
    hash_password,
    verify_password,
    create_user_token,
    get_current_user_id,
)
from core.database import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    ensure_demo_user,
    DEMO_USER_ID,
    DEMO_USER_EMAIL,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/signup", response_model=AuthResponse)
async def signup(req: SignupRequest):
    existing = await get_user_by_email(req.email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user_id = str(uuid.uuid4())
    await create_user(user_id, req.email, hash_password(req.password), req.name)

    token = create_user_token(user_id, req.email)
    return AuthResponse(
        access_token=token,
        user={"id": user_id, "email": req.email.lower().strip(), "name": req.name},
    )


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    user = await get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = create_user_token(user["id"], user["email"])
    return AuthResponse(
        access_token=token,
        user={"id": user["id"], "email": user["email"], "name": user["name"]},
    )


@router.post("/demo", response_model=AuthResponse)
async def demo_login():
    """Landing-page 'Watch Demo' button — no signup, drops the visitor
    straight into the pre-seeded demo dashboard (real Jira + sample
    GitHub/Slack/ServiceNow/Outlook data). Note this is one shared account:
    concurrent demo visitors see and can affect the same mutable state,
    same as the pre-existing 'demo' user the app already ran as a fallback
    before real per-user accounts existed."""
    await ensure_demo_user()
    token = create_user_token(DEMO_USER_ID, DEMO_USER_EMAIL)
    return AuthResponse(
        access_token=token,
        user={"id": DEMO_USER_ID, "email": DEMO_USER_EMAIL, "name": "Demo"},
    )


@router.get("/me")
async def me(user_id: str = Depends(get_current_user_id)):
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
