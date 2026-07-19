import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from core.config import settings
from core.state import save_trace
from core.connector_registry import connector_registry
from core.agent import run_pipeline_locked
from core.memory import memory_system

logger = logging.getLogger(__name__)

SCHEDULES: dict[str, int] = {
    "slack": 60,
    "outlook": 120,
    "jira": 300,
    "github": 300,
    "servicenow": 300,
    "transcript": 600,
}


class SyncEngine:
    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._last_event_count: dict[str, int] = {}
        self._user_last_counts: dict[str, int] = {}
        self._user_sync_semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_syncs))

    async def start(self):
        if self._running:
            return
        self._running = True
        logger.info("Sync engine starting with schedules: %s", SCHEDULES)

        for source_type, connector in connector_registry.items():
            interval = SCHEDULES.get(source_type, 300)
            self._tasks[source_type] = asyncio.create_task(
                self._sync_loop(source_type, connector, interval)
            )

        self._tasks["_user_connections"] = asyncio.create_task(self._user_sync_loop())

    async def stop(self):
        self._running = False
        for name, task in self._tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("Sync engine stopped")

    async def _sync_loop(self, source_type: str, connector, interval: int):
        while self._running:
            try:
                await self._sync_once(source_type, connector)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Sync loop %s error: %s", source_type, e)
            await asyncio.sleep(interval)

    async def _sync_once(self, source_type: str, connector) -> bool:
        start = datetime.now(timezone.utc)
        try:
            connected = await connector.connect()
            if not connected:
                logger.warning("Connector %s not connected, skipping sync", source_type)
                return False

            raw = await connector.fetch_tasks()
            if raw:
                event_count = len(raw)
                prev_count = self._last_event_count.get(source_type, 0)
                self._last_event_count[source_type] = event_count

                logger.info("Synced %d items from %s", len(raw), source_type)
                connector.last_sync = start.isoformat()

                if event_count != prev_count:
                    logger.info(
                        "New data detected from %s (%d -> %d) — reprioritizing",
                        source_type,
                        prev_count,
                        event_count,
                    )
                    await run_pipeline_locked()
                    memory_system.record_agent_memory(
                        "sync_engine",
                        f"last_detected_change_{source_type}",
                        f"{prev_count}->{event_count} at {datetime.now(timezone.utc).isoformat()}",
                    )
                else:
                    logger.info(
                        "No changes in %s (still %d items)", source_type, event_count
                    )
            return True
        except Exception as e:
            logger.error("Sync failed for %s: %s", source_type, e)
            connector.error = str(e)
            return False
        finally:
            elapsed = (datetime.now(timezone.utc) - start).total_seconds() * 1000
            await save_trace(f"sync_{source_type}", elapsed, status="ok")

    async def sync_now(self, source_type: Optional[str] = None):
        if source_type:
            connector = connector_registry.get(source_type)
            if connector:
                await self._sync_once(source_type, connector)
        else:
            for source_type, connector in connector_registry.items():
                await self._sync_once(source_type, connector)

    # ── Per-user connections (real Jira/GitHub/Slack/etc. a user connected
    # ── from Integrations) — the loops above only ever touch the shared/
    # ── demo connector, never an individual user's own OAuth/token
    # ── connection, so a new PR on someone's real repo was never picked up
    # ── without a manual "Generate Plan" click. This closes that gap. ──

    async def _user_sync_loop(self):
        interval = max(60, settings.pipeline_sync_interval_minutes * 60)
        while self._running:
            try:
                await self._sync_all_connected_users()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Per-user sync loop error: %s", e)
            await asyncio.sleep(interval)

    async def _sync_all_connected_users(self):
        from core.database import get_all_connected_user_ids

        user_ids = await get_all_connected_user_ids()
        if not user_ids:
            return
        await asyncio.gather(*(self._sync_user(uid) for uid in user_ids))

    async def _sync_user(self, user_id: str, force: bool = False) -> bool:
        """Fetch this user's own connected providers, and if the combined
        item count changed since we last checked, trigger a real
        reprioritization for them. Mirrors the shared-connector count-diff
        approach in _sync_once, scoped per user instead of globally.

        force=True (manual "Sync" clicks) always reprioritizes rather than
        only on a detected change — a user's first-ever sync has no prior
        count to compare against, and silently no-op'ing on that click would
        look broken even though there's real data to pull in.
        """
        async with self._user_sync_semaphore:
            from core.connections_service import build_all_user_connectors

            try:
                connectors = await build_all_user_connectors(user_id)
                total = 0
                for context_key, connector in connectors.items():
                    if connector is None:
                        continue
                    try:
                        connected = await connector.connect()
                        if not connected:
                            continue
                        raw = await connector.fetch_tasks()
                        total += len(raw or [])
                    except Exception as e:
                        logger.warning(
                            "Per-user sync fetch failed for %s/%s: %s",
                            user_id,
                            context_key,
                            e,
                        )

                prev = self._user_last_counts.get(user_id)
                self._user_last_counts[user_id] = total
                if force or (prev is not None and total != prev):
                    logger.info(
                        "Reprioritizing for user %s (%s -> %d items, forced=%s)",
                        user_id,
                        prev,
                        total,
                        force,
                    )
                    await run_pipeline_locked(user_id)
                    return True
                return False
            except Exception as e:
                logger.error("Per-user sync failed for %s: %s", user_id, e)
                return False

    async def sync_user_now(self, user_id: str) -> bool:
        """Manual 'Sync' trigger for a specific logged-in user's own
        connections (as opposed to sync_now(), which only ever touches the
        shared/demo connector)."""
        return await self._sync_user(user_id, force=True)


sync_engine = SyncEngine()
