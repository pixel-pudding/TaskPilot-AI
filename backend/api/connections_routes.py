from __future__ import annotations

import logging
import re
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from core.auth import get_current_user_id, create_state_token, verify_token
from core.config import settings
from core.connections_service import (
    save_connection,
    list_connections,
    remove_connection,
    validate_credentials,
    ALL_PROVIDERS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/connections", tags=["connections"])

# Only ever redirect back to a local dev origin or an explicitly allowlisted
# one — `origin` arrives as attacker-controllable query input, so it must be
# allowlisted rather than trusted outright (open-redirect guard). Production
# origins (e.g. a Vercel frontend) go in settings.additional_allowed_origins
# rather than here, so deploying to a new domain is a config change, not a
# code change.
_SAFE_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")


def _safe_origin(origin: str | None) -> str | None:
    if not origin:
        return None
    if _SAFE_ORIGIN_RE.match(origin):
        return origin
    allowed = {
        o.strip().rstrip("/")
        for o in settings.additional_allowed_origins.split(",")
        if o.strip()
    }
    if origin.rstrip("/") in allowed:
        return origin
    return None


def _frontend_redirect(query: dict, origin: str | None = None) -> RedirectResponse:
    base = _safe_origin(origin) or settings.frontend_url
    return RedirectResponse(f"{base}/integrations?{urlencode(query)}")


def _state_payload(state: str) -> dict:
    try:
        payload = verify_token(state)
    except HTTPException:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if payload.get("purpose") != "oauth_state":
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    return payload


def _state_user_id(state: str) -> str:
    return _state_payload(state)["sub"]


# ── Listing / removal ───────────────────────────────────────────────────────


@router.get("")
async def get_connections(user_id: str = Depends(get_current_user_id)):
    connections = await list_connections(user_id)
    connected_providers = {c["provider"] for c in connections}
    all_providers = [
        {"provider": p, "connected": p in connected_providers}
        for p in ALL_PROVIDERS
    ]
    return {"connections": connections, "providers": all_providers}


@router.delete("/{provider}")
async def disconnect(provider: str, user_id: str = Depends(get_current_user_id)):
    if provider not in ALL_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    removed = await remove_connection(user_id, provider)
    return {"status": "ok", "removed": removed}


# ── Token-paste providers: Jira, ServiceNow, Outlook ────────────────────────


class JiraCredentials(BaseModel):
    url: str
    email: str
    api_token: str


class ServiceNowCredentials(BaseModel):
    url: str
    username: str
    password: str


class OutlookCredentials(BaseModel):
    client_id: str
    client_secret: str
    tenant_id: str


@router.post("/jira")
async def connect_jira(creds: JiraCredentials, user_id: str = Depends(get_current_user_id)):
    ok, error = await validate_credentials("jira", creds.model_dump())
    if not ok:
        raise HTTPException(status_code=400, detail=f"Could not connect to Jira: {error}")
    await save_connection(user_id, "jira", "token", creds.model_dump(), account_label=creds.url)
    return {"status": "ok", "provider": "jira"}


@router.post("/servicenow")
async def connect_servicenow(
    creds: ServiceNowCredentials, user_id: str = Depends(get_current_user_id)
):
    ok, error = await validate_credentials("servicenow", creds.model_dump())
    if not ok:
        raise HTTPException(status_code=400, detail=f"Could not connect to ServiceNow: {error}")
    await save_connection(
        user_id, "servicenow", "token", creds.model_dump(), account_label=creds.url
    )
    return {"status": "ok", "provider": "servicenow"}


@router.post("/outlook")
async def connect_outlook(
    creds: OutlookCredentials, user_id: str = Depends(get_current_user_id)
):
    ok, error = await validate_credentials("outlook", creds.model_dump())
    if not ok:
        raise HTTPException(status_code=400, detail=f"Could not connect to Outlook: {error}")
    await save_connection(
        user_id, "outlook", "token", creds.model_dump(), account_label=creds.tenant_id
    )
    return {"status": "ok", "provider": "outlook"}


# ── GitHub OAuth ─────────────────────────────────────────────────────────────


@router.get("/github/authorize")
async def github_authorize(token: str = Query(...), origin: str | None = Query(None)):
    try:
        user_id = _state_user_id_from_bearer(token)
    except HTTPException:
        return _frontend_redirect({"connect_error": "github", "reason": "session_expired"}, origin)
    if not settings.github_oauth_client_id:
        return _frontend_redirect({"connect_error": "github", "reason": "not_configured"}, origin)
    state = create_state_token(user_id, _safe_origin(origin))
    params = {
        "client_id": settings.github_oauth_client_id,
        "redirect_uri": f"{settings.oauth_redirect_base_url}/api/connections/github/callback",
        "scope": "repo read:user",
        "state": state,
    }
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{urlencode(params)}")


@router.get("/github/callback")
async def github_callback(code: str = Query(...), state: str = Query(...)):
    payload = _state_payload(state)
    user_id = payload["sub"]
    origin = payload.get("return_origin")
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_oauth_client_id,
                "client_secret": settings.github_oauth_client_secret,
                "code": code,
                "redirect_uri": f"{settings.oauth_redirect_base_url}/api/connections/github/callback",
            },
        )
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            logger.error("GitHub OAuth token exchange failed: %s", token_data)
            return _frontend_redirect({"connect_error": "github"}, origin)

        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        login = user_resp.json().get("login", "") if user_resp.status_code == 200 else ""

    await save_connection(
        user_id, "github", "oauth", {"access_token": access_token}, account_label=login
    )
    return _frontend_redirect({"connected": "github"}, origin)


# ── Slack OAuth ──────────────────────────────────────────────────────────────


@router.get("/slack/authorize")
async def slack_authorize(token: str = Query(...), origin: str | None = Query(None)):
    try:
        user_id = _state_user_id_from_bearer(token)
    except HTTPException:
        return _frontend_redirect({"connect_error": "slack", "reason": "session_expired"}, origin)
    if not settings.slack_oauth_client_id:
        return _frontend_redirect({"connect_error": "slack", "reason": "not_configured"}, origin)
    state = create_state_token(user_id, _safe_origin(origin))
    params = {
        "client_id": settings.slack_oauth_client_id,
        "redirect_uri": f"{settings.oauth_redirect_base_url}/api/connections/slack/callback",
        "scope": "channels:history,channels:read,groups:history,groups:read",
        "state": state,
    }
    return RedirectResponse(f"https://slack.com/oauth/v2/authorize?{urlencode(params)}")


@router.get("/slack/callback")
async def slack_callback(code: str = Query(...), state: str = Query(...)):
    payload = _state_payload(state)
    user_id = payload["sub"]
    origin = payload.get("return_origin")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": settings.slack_oauth_client_id,
                "client_secret": settings.slack_oauth_client_secret,
                "code": code,
                "redirect_uri": f"{settings.oauth_redirect_base_url}/api/connections/slack/callback",
            },
        )
        data = resp.json()

    if not data.get("ok"):
        logger.error("Slack OAuth token exchange failed: %s", data)
        return _frontend_redirect({"connect_error": "slack"}, origin)

    access_token = data.get("access_token", "")
    team_name = data.get("team", {}).get("name", "")

    await save_connection(
        user_id, "slack", "oauth", {"access_token": access_token}, account_label=team_name
    )
    return _frontend_redirect({"connected": "slack"}, origin)


# ── Helper: full-page OAuth redirects can't send an Authorization header,
# ── so the frontend passes the JWT as a query param on the /authorize hit. ──


def _state_user_id_from_bearer(token: str) -> str:
    try:
        payload = verify_token(token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid or expired session — please log in again")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user_id
