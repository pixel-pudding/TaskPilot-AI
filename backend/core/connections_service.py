from __future__ import annotations

import logging
from typing import Any

from core.crypto import encrypt_dict, decrypt_dict
from core.database import (
    upsert_connection as db_upsert_connection,
    get_connections as db_get_connections,
    get_connection_credentials as db_get_connection_credentials,
    delete_connection as db_delete_connection,
)
from core.connectors.jira_connector import JiraConnector
from core.connectors.github_connector import GitHubConnector
from core.connectors.outlook_connector import OutlookConnector
from core.connectors.slack_connector import SlackConnector
from core.connectors.servicenow_connector import ServiceNowConnector
from core.connector_registry import connector_registry

logger = logging.getLogger(__name__)

# provider name (as stored in `connections`) -> pipeline context key
PROVIDER_TO_CONTEXT_KEY = {
    "jira": "jira",
    "servicenow": "defects",
    "outlook": "emails",
    "github": "github",
    "slack": "slack",
}

_CONNECTOR_CLASSES = {
    "jira": JiraConnector,
    "servicenow": ServiceNowConnector,
    "outlook": OutlookConnector,
    "github": GitHubConnector,
    "slack": SlackConnector,
}

ALL_PROVIDERS = list(_CONNECTOR_CLASSES.keys())


async def save_connection(
    user_id: str,
    provider: str,
    auth_type: str,
    credentials: dict[str, Any],
    account_label: str = "",
) -> None:
    if provider not in _CONNECTOR_CLASSES:
        raise ValueError(f"Unknown provider: {provider}")
    encrypted = encrypt_dict(credentials)
    await db_upsert_connection(user_id, provider, auth_type, encrypted, account_label)


async def list_connections(user_id: str) -> list[dict]:
    return await db_get_connections(user_id)


async def remove_connection(user_id: str, provider: str) -> bool:
    return await db_delete_connection(user_id, provider)


async def build_connector(user_id: str, provider: str):
    """Return a connector instance configured for this user.

    The reserved "demo" account (landing page's "Watch Demo" button) falls
    back to the shared demo/env-configured connector when it hasn't
    "connected" a provider, so visitors see the pre-seeded showcase data.
    Every real signed-up user gets None instead — no connection means no
    tasks from that source, full stop, so a new account starts genuinely
    empty rather than silently mixing in demo/mock data as if it were
    theirs."""
    # connector_registry is keyed by pipeline context key ("defects",
    # "emails"), not provider name ("servicenow", "outlook") — those two
    # differ, so falling back on the raw provider name silently returned
    # None for every user who hadn't personally connected ServiceNow/Outlook.
    registry_key = PROVIDER_TO_CONTEXT_KEY.get(provider, provider)

    encrypted = await db_get_connection_credentials(user_id, provider)
    if not encrypted:
        return connector_registry.get(registry_key) if user_id == "demo" else None

    creds = decrypt_dict(encrypted)
    if not creds:
        logger.warning("Could not decrypt stored credentials for %s/%s", user_id, provider)
        return connector_registry.get(registry_key) if user_id == "demo" else None

    connector_cls = _CONNECTOR_CLASSES[provider]
    connector = connector_cls()
    connector.configure(creds)
    return connector


async def build_all_user_connectors(user_id: str) -> dict[str, Any]:
    """Build the full set of connectors for a pipeline run: the "demo"
    account gets the shared/env-configured connectors as a showcase; every
    real user gets only what they've personally connected — nothing else."""
    connectors: dict[str, Any] = {}
    for provider, context_key in PROVIDER_TO_CONTEXT_KEY.items():
        connectors[context_key] = await build_connector(user_id, provider)
    # transcript isn't user-connectable at all yet, so it's demo-only —
    # a real user has no way to supply their own, and showing them the
    # shared simulated transcript would inject fabricated tasks into what
    # should be an empty, honest dashboard.
    connectors["transcript"] = connector_registry.get("transcript") if user_id == "demo" else None
    return connectors


async def validate_credentials(provider: str, credentials: dict[str, Any]) -> tuple[bool, str]:
    """Instantiate a connector with these creds and try to actually connect,
    so we don't save a token-paste connection that doesn't work."""
    if provider not in _CONNECTOR_CLASSES:
        return False, f"Unknown provider: {provider}"
    connector = _CONNECTOR_CLASSES[provider]()
    connector.configure(credentials)
    ok = await connector.connect()
    return ok, connector.error or ("" if ok else "Connection failed")
