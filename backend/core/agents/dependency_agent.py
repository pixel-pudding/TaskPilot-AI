"""
DependencyAgent — infers blocking relationships from unstructured text.

Every source connector except Jira (via issuelinks) leaves .dependencies/
.blocks empty, even though Slack messages, emails, and meeting transcripts
are full of narrative blocking language ("waiting on X", "blocked by Y").
This agent makes one batched LLM call over the whole deduped task list (not
one call per pair — that's the same N² explosion already fixed in dedup)
and fills in relationships it can find, merging with whatever a connector
already populated rather than overwriting it.
"""

import json
import logging
from typing import Any

from core.agents.base import BaseAgent
from core.llm_client import call_llm
from core.prompts import build_dependency_inference_prompt

logger = logging.getLogger(__name__)

# Keeps the single batched prompt within this account's tight per-minute
# Groq token budget — same constraint that forced MAX_CONTEXT_TASKS down
# in core/qa.py for chat.
MAX_TASKS_FOR_INFERENCE = 60


class DependencyAgent(BaseAgent):
    name = "dependency_inference"

    async def process(self, context: dict[str, Any]) -> dict[str, Any]:
        tasks = context.get("deduped_tasks", [])
        if not tasks:
            return {"deduped_tasks": tasks}

        candidates = tasks[:MAX_TASKS_FOR_INFERENCE]
        task_by_id = {t.id: t for t in tasks}
        inferred_count = 0

        try:
            task_dicts = [t.model_dump(mode="json") for t in candidates]
            system, user = build_dependency_inference_prompt(task_dicts)
            response = await call_llm(
                prompt=user,
                system=system,
                json_mode=True,
                temperature=0.1,
                max_output_tokens=1024,
            )

            parsed = response.parsed_json
            if parsed is None:
                try:
                    parsed = json.loads(response.text)
                except Exception:
                    logger.warning(
                        "DependencyAgent: could not parse JSON — %s", response.text[:200]
                    )
                    parsed = {}

            relationships = parsed.get("relationships", []) if isinstance(parsed, dict) else []

            for rel in relationships:
                blocked_id = rel.get("blocked_task_id")
                blocking_id = rel.get("blocking_task_id")
                if not blocked_id or not blocking_id or blocked_id == blocking_id:
                    continue

                blocked_task = task_by_id.get(blocked_id)
                blocking_task = task_by_id.get(blocking_id)
                if not blocked_task or not blocking_task:
                    # LLM referenced an id outside the known set — ignore
                    # rather than trusting a possibly-hallucinated id.
                    continue

                if blocking_id not in blocked_task.dependencies:
                    blocked_task.dependencies = list(blocked_task.dependencies) + [blocking_id]
                    inferred_count += 1
                if blocked_id not in blocking_task.blocks:
                    blocking_task.blocks = list(blocking_task.blocks) + [blocked_id]

            if inferred_count:
                logger.info(
                    "DependencyAgent: inferred %d blocking relationship(s) from task text",
                    inferred_count,
                )
            self.remember("last_inferred_count", str(inferred_count))

        except Exception as e:
            # Never let a flaky LLM call break the pipeline — tasks keep
            # whatever dependencies their connector already gave them.
            logger.warning(
                "DependencyAgent: inference failed, leaving dependencies as-is: %s", e
            )

        return {"deduped_tasks": tasks}

    async def reflect(self, context: dict[str, Any]) -> dict[str, Any]:
        reflection = await super().reflect(context)
        tasks = context.get("deduped_tasks", [])
        with_deps = sum(1 for t in tasks if t.dependencies)
        reflection["observations"] = [
            f"{len(tasks)} tasks available; {with_deps} already have known "
            "dependencies (e.g. from Jira issue links)"
        ]
        last = self.recall("last_inferred_count")
        if last:
            reflection["observations"].append(
                f"Previous run inferred {last} relationship(s) from unstructured text"
            )
        return reflection

    async def verify(self, result: dict[str, Any]) -> dict[str, Any]:
        tasks = result.get("deduped_tasks", [])
        issues = []
        for t in tasks:
            if t.id in t.dependencies:
                issues.append(f"Task {t.id} lists itself as a dependency")
        return {
            "verified": len(issues) == 0,
            "agent": self.name,
            "issues": issues,
        }
