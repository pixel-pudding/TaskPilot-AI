from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from models.task import (
    ChatRequest,
    InjectRequest,
    ConvertHiddenRequest,
    Task,
    CreateTaskRequest,
    UpdateTaskRequest,
)
from core.auth import get_current_user_id, verify_token
from core.state import store, get_recent_traces, get_team_velocity
from core.state import (
    save_chat_log,
    save_feedback,
    get_user_preference_boosts,
    get_daily_snapshots,
    save_state,
)
from core.agent import run_pipeline, ensure_plan, run_pipeline_locked, reprioritize_with_injection
from core.qa import answer_question
from core.sync_engine import sync_engine
from core.observability import get_metrics_summary, get_connector_status
from core.websocket_manager import ws_manager
from core.dependency_analyzer import DependencyAnalyzer
from core.memory import memory_system
from core.calendar_planner import CalendarPlanner
from core.prometheus_metrics import (
    task_count,
    extracted_task_count,
    active_websocket_connections,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = Query(None)):
    # Each user gets their own channel (user:<id>) so a plan/task update for
    # one user is never pushed to another user's browser tab. WebSocket
    # handshakes can't carry an Authorization header, so the JWT travels as
    # a query param, same pattern as the OAuth /authorize redirects.
    user_id: str | None = None
    if token:
        try:
            payload = verify_token(token)
            user_id = payload.get("sub")
        except Exception:
            user_id = None
    channel = f"user:{user_id}" if user_id else "broadcast"

    await ws_manager.connect(websocket, channel=channel)
    active_websocket_connections.inc()
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                event = msg.get("event", "")
                if event == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))
                elif event == "refresh":
                    await run_pipeline_locked(user_id or "demo")
            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.error("WebSocket message error: %s", e)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel=channel)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        ws_manager.disconnect(websocket, channel=channel)
    finally:
        active_websocket_connections.dec()


@router.get("/api/health")
async def health():
    import os

    summary = store.get_state_summary()
    connector_status = get_connector_status()

    jira_c = next((c for c in connector_status if c["name"] == "Jira"), {})
    github_c = next((c for c in connector_status if c["name"] == "GitHub"), {})

    llm_key = os.environ.get("LLM_API_KEY") or os.environ.get("XAI_API_KEY", "")

    from core.cache import health_check as redis_health

    redis_ok = await redis_health()

    from core.database import engine

    db_ok = engine is not None

    return {
        "status": "ok",
        "version": "1.0.0",
        "jira_connected": bool(jira_c.get("connected", False)),
        "github_connected": bool(github_c.get("connected", False)),
        "grok_connected": bool(llm_key),
        "redis_connected": redis_ok,
        "database_connected": db_ok,
        "task_count": summary["task_count"],
        "last_sync": summary["last_run"],
        "uptime_seconds": (
            datetime.now(timezone.utc) - store._startup_time
        ).total_seconds()
        if hasattr(store, "_startup_time")
        else 0,
        "connectors": connector_status,
    }


@router.get("/api/health/live")
async def health_live():
    return {"status": "alive"}


@router.get("/api/health/ready")
async def health_ready():
    from core.database import engine
    from core.cache import health_check as redis_health

    db_ok = engine is not None
    redis_ok = await redis_health()

    if not db_ok:
        raise HTTPException(status_code=503, detail="Database not ready")
    if not redis_ok:
        raise HTTPException(status_code=503, detail="Redis not ready")

    return {"status": "ready"}


@router.post("/api/refresh")
async def refresh(user_id: str = Depends(get_current_user_id)):
    try:
        plan = await run_pipeline_locked(user_id)
        user_state = store.for_user(user_id)
        task_count.set(len(user_state.current_tasks))
        extracted = sum(
            1
            for t in user_state.current_tasks
            if t.confidence is not None and t.confidence > 0
        )
        extracted_task_count.set(extracted)
        return plan
    except Exception as e:
        logger.exception("Pipeline refresh failed")
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")


@router.get("/api/plan")
async def get_plan(user_id: str = Depends(get_current_user_id)):
    try:
        return await ensure_plan(user_id)
    except Exception as e:
        logger.exception("Pipeline auto-trigger failed")
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")


@router.get("/api/tasks")
async def get_tasks(
    source_type: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, description="Max tasks to return"),
    offset: Optional[int] = Query(0, description="Pagination offset"),
    user_id: str = Depends(get_current_user_id),
):
    all_tasks = store.for_user(user_id).current_tasks
    if source_type:
        all_tasks = [t for t in all_tasks if t.source_type == source_type]
    if priority:
        all_tasks = [t for t in all_tasks if t.priority == priority]
    if status:
        all_tasks = [t for t in all_tasks if t.status == status]
    total = len(all_tasks)
    if offset:
        all_tasks = all_tasks[offset:]
    if limit:
        all_tasks = all_tasks[:limit]
    return {"tasks": all_tasks, "total": total, "limit": limit, "offset": offset}


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str, user_id: str = Depends(get_current_user_id)):
    for t in store.for_user(user_id).current_tasks:
        if t.id == task_id:
            return t
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


@router.put("/api/tasks/{task_id}")
async def update_task(
    task_id: str, req: UpdateTaskRequest, user_id: str = Depends(get_current_user_id)
):
    user_state = store.for_user(user_id)
    for t in user_state.current_tasks:
        if t.id == task_id:
            if req.title is not None:
                t.title = req.title
            if req.description is not None:
                t.description = req.description
            if req.priority is not None:
                t.priority = req.priority
            if req.status is not None:
                t.status = req.status
            if req.deadline is not None:
                t.deadline = req.deadline
            if req.owner is not None:
                t.owner = req.owner
            if req.assignee is not None:
                t.assignee = req.assignee
            if req.team is not None:
                t.team = req.team
            await save_state(user_state.current_tasks, user_state.current_plan, user_id=user_id)
            await ws_manager.broadcast(
                "broadcast",
                "tasks_updated",
                [t.model_dump(mode="json") for t in user_state.current_tasks],
            )
            from core.notification_service import notification_service

            notification_service.schedule(narrative=f"Updated task '{t.title}'")
            return {"status": "ok", "task": t}
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


@router.post("/api/tasks")
async def create_task(req: CreateTaskRequest, user_id: str = Depends(get_current_user_id)):
    user_state = store.for_user(user_id)
    task = Task(
        id=f"T{len(user_state.current_tasks) + 1:04d}",
        title=req.title,
        description=req.description or "",
        source_type=req.source_type or "injected",
        source=req.source or "manual",
        priority=req.priority,
        status=req.status or "open",
        deadline=req.deadline,
        owner=req.owner,
        assignee=req.assignee,
        team=req.team,
    )
    user_state.current_tasks.append(task)
    await save_state(user_state.current_tasks, user_state.current_plan, user_id=user_id)
    await ws_manager.broadcast(
        "broadcast",
        "tasks_updated",
        [t.model_dump(mode="json") for t in user_state.current_tasks],
    )
    from core.notification_service import notification_service

    notification_service.schedule(narrative=f"Created task '{task.title}'")
    return {"status": "ok", "task": task}


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, user_id: str = Depends(get_current_user_id)):
    user_state = store.for_user(user_id)
    for i, t in enumerate(user_state.current_tasks):
        if t.id == task_id:
            removed = user_state.current_tasks.pop(i)
            await save_state(user_state.current_tasks, user_state.current_plan, user_id=user_id)
            await ws_manager.broadcast(
                "broadcast",
                "tasks_updated",
                [t.model_dump(mode="json") for t in user_state.current_tasks],
            )
            from core.notification_service import notification_service

            notification_service.schedule(narrative=f"Deleted task '{removed.title}'")
            return {"status": "ok", "task_id": task_id, "title": removed.title}
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


@router.put("/api/tasks/reorder")
async def reorder_tasks(data: dict, user_id: str = Depends(get_current_user_id)):
    user_state = store.for_user(user_id)
    task_ids = data.get("task_ids", [])
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids required")
    task_map = {t.id: t for t in user_state.current_tasks}
    reordered = [task_map[tid] for tid in task_ids if tid in task_map]
    if len(reordered) != len(task_ids):
        raise HTTPException(status_code=400, detail="Some task IDs not found")
    user_state.current_tasks = reordered
    await save_state(user_state.current_tasks, user_state.current_plan, user_id=user_id)
    await ws_manager.broadcast(
        "broadcast",
        "tasks_updated",
        [t.model_dump(mode="json") for t in user_state.current_tasks],
    )
    return {"status": "ok", "count": len(reordered)}


@router.get("/api/team-metrics")
async def get_team_metrics(user_id: str = Depends(get_current_user_id)):
    tasks = store.for_user(user_id).current_tasks
    if not tasks:
        return {"teams": {}}

    team_stats = {}
    for task in tasks:
        team = task.team or "unassigned"
        assignee = task.assignee or "unassigned"

        if team not in team_stats:
            team_stats[team] = {
                "members": {},
                "total_tasks": 0,
                "blocked": 0,
                "done": 0,
                "in_progress": 0,
            }

        if assignee not in team_stats[team]["members"]:
            team_stats[team]["members"][assignee] = {
                "tasks": 0,
                "blocked": 0,
                "done": 0,
                "priority_counts": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
            }

        team_stats[team]["members"][assignee]["tasks"] += 1
        team_stats[team]["total_tasks"] += 1

        if task.status == "blocked":
            team_stats[team]["members"][assignee]["blocked"] += 1
            team_stats[team]["blocked"] += 1
        if task.status == "done":
            team_stats[team]["members"][assignee]["done"] += 1
            team_stats[team]["done"] += 1
        if task.status == "in_progress":
            team_stats[team]["in_progress"] += 1

        if task.priority:
            team_stats[team]["members"][assignee]["priority_counts"][task.priority] = (
                team_stats[team]["members"][assignee]["priority_counts"].get(
                    task.priority, 0
                )
                + 1
            )

    return {"teams": team_stats}


@router.get("/api/dashboard")
async def get_dashboard(user_id: str = Depends(get_current_user_id)):
    try:
        plan = await ensure_plan(user_id)
    except Exception as e:
        logger.exception("Pipeline auto-trigger failed")
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

    user_state = store.for_user(user_id)
    tasks = user_state.current_tasks

    ranked = plan.ranked_tasks if plan else []
    dependencies = DependencyAnalyzer.compute_blocking_impact(tasks) if tasks else {}
    critical_path = DependencyAnalyzer.find_critical_path(tasks) if tasks else []
    leverage = DependencyAnalyzer.find_highest_leverage_tasks(tasks) if tasks else []
    unblocking = (
        DependencyAnalyzer.get_unblocking_recommendations(tasks) if tasks else []
    )
    deferred = memory_system.detect_deferred_tasks(tasks)
    velocity = await get_team_velocity()
    patterns = memory_system.get_completion_patterns()
    preferences = memory_system.get_all_preferences()

    time_blocks = (
        CalendarPlanner.generate_time_blocked_plan(ranked[: min(6, len(ranked))])
        if ranked
        else None
    )
    today_events = CalendarPlanner.get_todays_events()

    return {
        "plan": plan,
        "dependency_analysis": {
            "critical_path": critical_path,
            "blocking_impacts": dependencies,
            "highest_leverage_tasks": leverage,
            "unblocking_recommendations": unblocking,
        },
        "time_blocked_plan": time_blocks,
        "today_calendar_events": today_events,
        "deferred_tasks": deferred,
        "team_velocity": velocity,
        "completion_patterns": patterns,
        "user_preferences": preferences,
    }


@router.post("/api/chat")
async def chat(req: ChatRequest, user_id: str = Depends(get_current_user_id)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    try:
        user_state = store.for_user(user_id)
        if user_state.current_plan is None:
            await run_pipeline(user_id)
            user_state = store.for_user(user_id)
        tasks = user_state.current_tasks
        response = await answer_question(tasks, req.message, user_state.chat_history[-5:])
        user_state.add_chat_entry(req.message, response.answer, response.referenced_task_ids)
        await save_chat_log(
            req.message, response.answer, response.referenced_task_ids, user_id=user_id
        )
        return response
    except Exception as e:
        logger.exception("Chat failed")
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}")


@router.post("/api/inject")
async def inject(req: InjectRequest, user_id: str = Depends(get_current_user_id)):
    try:
        user_state = store.for_user(user_id)
        if user_state.current_plan is None:
            raise HTTPException(
                status_code=400, detail="No plan exists — call /api/refresh first"
            )

        new_plan = await reprioritize_with_injection(req, user_id)

        return new_plan.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Inject failed")
        raise HTTPException(status_code=500, detail=f"Inject failed: {e}")


@router.post("/api/feedback")
async def submit_feedback(feedback: dict, user_id: str = Depends(get_current_user_id)):
    await save_feedback(
        task_id=feedback.get("task_id", ""),
        action=feedback.get("action", "upvote"),
        preference=feedback.get("preference", "general"),
    )
    memory_system.learn_from_feedback(
        task_id=feedback.get("task_id", ""),
        action=feedback.get("action", "upvote"),
        preference=feedback.get("preference", "general"),
    )
    return {"status": "ok", "message": "Feedback recorded"}


@router.get("/api/feedback/preferences")
async def feedback_preferences():
    boosts = await get_user_preference_boosts()
    return {"boosts": boosts}


@router.get("/api/traces")
async def get_traces():
    try:
        return await get_recent_traces(limit=50)
    except Exception:
        return []


@router.get("/api/weekly-summary")
async def weekly_summary(user_id: str = Depends(get_current_user_id)):
    try:
        from core.weekly_summary import generate_weekly_summary

        user_state = store.for_user(user_id)
        daily_plans = await get_daily_snapshots(days=7)
        if not daily_plans and user_state.current_plan:
            daily_plans.append(
                {
                    "date": user_state.current_plan.generated_at,
                    "top_3": [
                        {"id": t.id, "title": t.title, "status": t.status}
                        for t in user_state.current_plan.top_priorities
                    ],
                    "completed": [],
                    "deferred": [
                        {"id": t.id, "title": t.title}
                        for t in user_state.current_plan.deferred
                    ],
                    "blockers": [
                        {"id": t.id, "title": t.title, "blocked_by": ""}
                        for t in user_state.current_plan.blocked
                    ],
                }
            )
        summary = await generate_weekly_summary(daily_plans)
        return {
            "summary": summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning("Weekly summary module failed: %s", e)
        return {"summary": "Weekly summary module not available.", "generated_at": None}


@router.get("/api/extractions/recent")
async def get_recent_extractions(user_id: str = Depends(get_current_user_id)):
    tasks = [
        t
        for t in store.for_user(user_id).current_tasks
        if t.raw_text and len(t.raw_text) > 20
    ]
    return {
        "extractions": [
            {
                "task_id": t.id,
                "raw_text": t.raw_text,
                "title": t.title,
                "source_type": t.source_type,
                "source": t.source,
                "confidence": t.confidence or 0,
                "priority": t.priority,
                "deadline": t.deadline,
                "status": t.status,
                "source_sentence": t.source_sentence,
                "grounded": t.grounded,
                "grounding_confidence": t.grounding_confidence,
            }
            for t in tasks
        ],
        "total": len(tasks),
    }


@router.post("/api/hidden-tasks/convert")
async def convert_hidden_task(
    req: ConvertHiddenRequest, user_id: str = Depends(get_current_user_id)
):
    try:
        user_state = store.for_user(user_id)
        task = next((t for t in user_state.current_tasks if t.id == req.task_id), None)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        task.raw_text = ""
        if req.title:
            task.title = req.title
        if req.priority:
            task.priority = req.priority
        if req.deadline:
            task.deadline = req.deadline
        await save_state(user_state.current_tasks, user_state.current_plan, user_id=user_id)
        await ws_manager.broadcast(
            "broadcast",
            "tasks_updated",
            [t.model_dump(mode="json") for t in user_state.current_tasks],
        )
        from core.notification_service import notification_service

        notification_service.schedule(
            narrative=f"Converted hidden task '{task.title}' into tracked task"
        )
        return {"status": "ok", "task_id": task.id, "title": task.title}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Convert hidden task failed")
        raise HTTPException(status_code=500, detail=f"Convert failed: {e}")


@router.get("/api/sources")
async def get_sources(user_id: str = Depends(get_current_user_id)):
    from core.connections_service import list_connections, ALL_PROVIDERS

    connector_status = get_connector_status()
    user_connections = {c["provider"]: c for c in await list_connections(user_id)}

    status_colors = {
        "Jira": "#2684ff",
        "ServiceNow": "#62d84e",
        "Outlook": "#0078d4",
        "GitHub": "#ffffff",
        "Slack": "#4a154b",
        "Meeting Transcripts": "#ff6b35",
    }
    name_to_provider = {
        "Jira": "jira",
        "ServiceNow": "servicenow",
        "Outlook": "outlook",
        "GitHub": "github",
        "Slack": "slack",
    }
    sources = []
    for c in connector_status:
        provider = name_to_provider.get(c["name"])
        own_connection = user_connections.get(provider) if provider else None
        if own_connection:
            sources.append(
                {
                    "name": c["name"],
                    "color": status_colors.get(c["name"], "#888888"),
                    "status": "Synced" if own_connection["status"] == "connected" else "Error",
                    "last_sync": own_connection.get("last_sync"),
                    "error": own_connection.get("error"),
                    "account_label": own_connection.get("account_label"),
                    "own_connection": True,
                }
            )
        else:
            sources.append(
                {
                    "name": c["name"],
                    "color": status_colors.get(c["name"], "#888888"),
                    "status": "Synced" if c["connected"] else "Disconnected",
                    "last_sync": c["last_sync"],
                    "error": c["error"],
                    "account_label": None,
                    "own_connection": False,
                }
            )
    return {
        "sources": sources,
        "total_tasks": len(store.for_user(user_id).current_tasks),
    }


@router.get("/api/sync/status")
async def sync_status():
    return {"connectors": get_connector_status()}


@router.post("/api/sync/now")
async def sync_now(
    source_type: Optional[str] = None, user_id: str = Depends(get_current_user_id)
):
    await sync_engine.sync_now(source_type)
    # The shared-connector sync above only covers the demo/env-configured
    # fallback data — also check this user's own real connections so a
    # manual "Sync" click actually picks up new activity on their account.
    await sync_engine.sync_user_now(user_id)
    return {
        "status": "ok",
        "message": f"Sync triggered for {source_type or 'all'} connectors",
    }


@router.get("/api/metrics")
async def metrics():
    return get_metrics_summary()


@router.get("/api/memory/preferences")
async def get_memory_preferences():
    return {"preferences": memory_system.get_all_preferences()}


@router.get("/api/memory/completion-patterns")
async def get_completion_patterns():
    return memory_system.get_completion_patterns()


@router.get("/api/memory/deferred-tasks")
async def get_deferred_tasks(user_id: str = Depends(get_current_user_id)):
    tasks = store.for_user(user_id).current_tasks
    return {"deferred_tasks": memory_system.detect_deferred_tasks(tasks)}


@router.get("/api/calendar/today")
async def get_calendar_today():
    events = CalendarPlanner.get_todays_events()
    slots = CalendarPlanner.get_unavailable_slots()
    return {"events": events, "unavailable_slots": slots}


@router.get("/api/dedup-groups")
async def get_dedup_groups(user_id: str = Depends(get_current_user_id)):
    tasks = store.for_user(user_id).current_tasks
    groups: dict[str, dict] = {}
    for t in tasks:
        gid = t.dedup_group
        if not gid:
            continue
        if gid not in groups:
            groups[gid] = {
                "id": gid,
                "merged_count": 0,
                "match_confidence": 0.0,
                "reasoning": "",
                "tasks": [],
            }
        groups[gid]["tasks"].append(
            {
                "id": t.id,
                "title": t.title,
                "source": t.source_type,
                "snippet": (t.raw_text or t.description or "")[:160],
                "priority": t.priority,
                "status": t.status,
                "deadline": t.deadline,
                "owner": t.owner,
            }
        )
        if getattr(t, "dedup_members", None):
            for member in t.dedup_members:
                groups[gid]["tasks"].append({
                    "id": member.get("task_id", ""),
                    "title": member.get("title", ""),
                    "source": member.get("source_type") or member.get("source", ""),
                    "snippet": member.get("snippet", ""),
                    "priority": None,
                    "status": "merged",
                    "deadline": None,
                    "owner": None,
                })

        groups[gid]["merged_count"] = len(groups[gid]["tasks"])
        if (
            t.dedup_confidence is not None
            and t.dedup_confidence > groups[gid]["match_confidence"]
        ):
            groups[gid]["match_confidence"] = t.dedup_confidence
        if t.dedup_explanation:
            groups[gid]["reasoning"] = t.dedup_explanation
    return {"groups": list(groups.values())}


@router.get("/api/dependency-analysis")
async def get_dependency_analysis(user_id: str = Depends(get_current_user_id)):
    tasks = store.for_user(user_id).current_tasks
    if not tasks:
        return {"error": "No tasks available"}
    return {
        "critical_path": DependencyAnalyzer.find_critical_path(tasks),
        "blocking_impacts": DependencyAnalyzer.compute_blocking_impact(tasks),
        "highest_leverage_tasks": DependencyAnalyzer.find_highest_leverage_tasks(tasks),
        "unblocking_recommendations": DependencyAnalyzer.get_unblocking_recommendations(
            tasks
        ),
    }


# ─── A2A Protocol ────────────────────────────────────────────────────────────────

A2A_AGENTS: dict[str, dict] = {}


@router.get("/api/a2a/status")
async def a2a_status():
    return {
        "status": "connected" if len(A2A_AGENTS) > 0 else "standalone",
        "agent_id": "taskpilot-ai",
        "agents_connected": len(A2A_AGENTS),
        "agents": list(A2A_AGENTS.values()),
    }


@router.post("/api/a2a/register")
async def a2a_register(data: dict):
    agent_id = data.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id required")
    A2A_AGENTS[agent_id] = {
        "agent_id": agent_id,
        "capabilities": data.get("capabilities", {}),
        "endpoint": data.get("endpoint", ""),
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("A2A agent registered: %s", agent_id)
    return {"status": "ok", "agent_id": agent_id}


@router.post("/api/a2a/message")
async def a2a_message(data: dict):
    target = data.get("target_agent")
    message_type = data.get("type", "task_query")
    if target and target != "taskpilot-ai":
        agent = A2A_AGENTS.get(target)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {target} not found")
        return {"status": "forwarded", "target": target}

    if message_type == "task_query":
        tasks = store.current_tasks[:10]
        return {
            "status": "success",
            "data": [
                {
                    "id": t.id,
                    "title": t.title,
                    "priority": t.priority,
                    "status": t.status,
                    "source_type": t.source_type,
                }
                for t in tasks
            ],
            "agent": "taskpilot-ai",
            "count": len(tasks),
        }
    elif message_type == "priority_query":
        plan = store.current_plan
        return {
            "status": "success",
            "data": [
                {"id": t.id, "title": t.title, "score": t.score}
                for t in (plan.top_priorities if plan else [])
            ],
            "agent": "taskpilot-ai",
        }
    elif message_type == "dependency_query":
        tasks = store.current_tasks
        return {
            "status": "success",
            "data": DependencyAnalyzer.compute_blocking_impact(tasks) if tasks else {},
            "agent": "taskpilot-ai",
        }
    return {"status": "error", "message": f"Unknown message type: {message_type}"}
