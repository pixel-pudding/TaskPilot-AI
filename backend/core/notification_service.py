import asyncio
import json
import logging
from typing import Any

from core.websocket_manager import ws_manager
from models.task import Task

logger = logging.getLogger(__name__)


def _as_json(obj: Any) -> Any:
    if isinstance(obj, Task):
        return obj.model_dump(mode="json")
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def _channel_for(user_id: str) -> str:
    return f"user:{user_id}" if user_id else "broadcast"


class NotificationService:
    """Debounces and dispatches plan/task/alert updates over WebSocket.

    Pending changes and debounce timers are keyed per user_id — a shared
    global buffer would let one user's pipeline completion clobber or merge
    with another's mid-flight update, and (before per-user channels existed)
    every connected browser tab received every broadcast regardless of whose
    data it was.
    """

    def __init__(self):
        self._debounce_timers: dict[str, asyncio.TimerHandle] = {}
        self._pending: dict[str, dict[str, Any]] = {}
        self._last_alerts_hash: dict[str, str] = {}
        self._last_tasks_hash: dict[str, str] = {}
        self._broadcast_lock = asyncio.Lock()

    def _hash(self, data: Any) -> str:
        raw = json.dumps(data, default=str, sort_keys=True)
        return str(hash(raw))

    def _coalesced_dispatch(self, user_id: str):
        pending = self._pending.pop(user_id, {})
        self._debounce_timers.pop(user_id, None)
        if pending and self._running_loop():
            asyncio.create_task(self._dispatch_all(user_id, pending))

    async def _dispatch_all(self, user_id: str, pending: dict[str, Any]):
        channel = _channel_for(user_id)
        try:
            if "plan" in pending:
                plan_data = _as_json(pending["plan"])
                await ws_manager.broadcast_plan(plan_data, channel=channel)

            if "tasks" in pending:
                tasks_data = [_as_json(t) for t in pending["tasks"]]
                async with self._broadcast_lock:
                    h = self._hash(tasks_data)
                    if h != self._last_tasks_hash.get(user_id):
                        self._last_tasks_hash[user_id] = h
                        await ws_manager.broadcast_task_list(tasks_data, channel=channel)
                        await ws_manager.broadcast_priorities(tasks_data, channel=channel)

            if "alerts" in pending:
                alerts_data = [_as_json(a) for a in pending["alerts"]]
                async with self._broadcast_lock:
                    h = self._hash(alerts_data)
                    if h != self._last_alerts_hash.get(user_id):
                        self._last_alerts_hash[user_id] = h
                        await ws_manager.broadcast_alerts(alerts_data, channel=channel)

            narrative = pending.get("narrative")
            if narrative:
                await ws_manager.broadcast(channel, "narrative_alert", narrative)
        except Exception as e:
            logger.warning("Notification dispatch failed (user=%s): %s", user_id, e)

    def schedule(self, user_id: str = "demo", **changes: Any):
        self._pending.setdefault(user_id, {}).update(changes)
        existing = self._debounce_timers.get(user_id)
        if existing:
            existing.cancel()
        if self._running_loop():
            self._debounce_timers[user_id] = asyncio.get_running_loop().call_later(
                0.5, self._coalesced_dispatch, user_id
            )

    @staticmethod
    def _running_loop() -> bool:
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    async def broadcast_alerts_now(self, alerts: list, user_id: str = "demo"):
        channel = _channel_for(user_id)
        alerts_data = [_as_json(a) for a in alerts]
        async with self._broadcast_lock:
            h = self._hash(alerts_data)
            if h != self._last_alerts_hash.get(user_id):
                self._last_alerts_hash[user_id] = h
                await ws_manager.broadcast_alerts(alerts_data, channel=channel)

    async def broadcast_status_now(self, status: dict[str, Any]):
        # System health isn't per-user data — stays on the shared channel.
        await ws_manager.broadcast("broadcast", "system_status", status)


notification_service = NotificationService()
