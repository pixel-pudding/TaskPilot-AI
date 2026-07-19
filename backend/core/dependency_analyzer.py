from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any

from models.task import Task

logger = logging.getLogger(__name__)


class DependencyAnalyzer:
    @staticmethod
    def build_adjacency_lists(
        tasks: list[Task],
    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        depends_on: dict[str, list[str]] = {
            t.id: list(t.dependencies or []) for t in tasks
        }
        blocked_by: dict[str, list[str]] = defaultdict(list)
        for t in tasks:
            for dep_id in t.dependencies or []:
                blocked_by[dep_id].append(t.id)
        return depends_on, blocked_by

    @staticmethod
    def find_critical_path(tasks: list[Task]) -> list[str]:
        """The longest chain of dependent tasks (the actual "critical path"),
        not merely a topological ordering.

        A plain topological sort of a graph with no edges still succeeds —
        every node trivially has in-degree 0, so it produces "all tasks, in
        some order," which reads as one enormous fake dependency chain
        exactly when there's no real dependency data at all. This computes
        the longest path via DP over the topological order instead, and
        returns [] when no chain of 2+ tasks actually exists.
        """
        if not tasks:
            return []

        depends_on, _ = DependencyAnalyzer.build_adjacency_lists(tasks)
        task_ids = {t.id for t in tasks}
        depends_on = {
            tid: [d for d in deps if d in task_ids] for tid, deps in depends_on.items()
        }

        # Reverse adjacency: which tasks does completing `node` unblock?
        unblocks: dict[str, list[str]] = defaultdict(list)
        for tid, deps in depends_on.items():
            for d in deps:
                unblocks[d].append(tid)

        in_degree: dict[str, int] = {tid: len(deps) for tid, deps in depends_on.items()}
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        topo_order: list[str] = []

        while queue:
            node = queue.popleft()
            topo_order.append(node)
            for nxt in unblocks.get(node, []):
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        # Longest chain ending at each node: since topo_order guarantees every
        # dependency of `node` was already visited, its longest-chain value
        # is already finalized by the time we reach `node`.
        longest_ending_at: dict[str, int] = {tid: 1 for tid in task_ids}
        predecessor: dict[str, str | None] = {tid: None for tid in task_ids}
        for node in topo_order:
            for dep in depends_on.get(node, []):
                if longest_ending_at[dep] + 1 > longest_ending_at[node]:
                    longest_ending_at[node] = longest_ending_at[dep] + 1
                    predecessor[node] = dep

        if not topo_order:
            return []

        end = max(topo_order, key=lambda tid: longest_ending_at[tid])
        if longest_ending_at[end] <= 1:
            # No chain of 2+ tasks exists anywhere — nothing to call a
            # "critical path."
            return []

        path = []
        cur: str | None = end
        while cur is not None:
            path.append(cur)
            cur = predecessor[cur]
        path.reverse()
        return path

    @staticmethod
    def compute_blocking_impact(tasks: list[Task]) -> dict[str, dict[str, Any]]:
        _, blocked_by = DependencyAnalyzer.build_adjacency_lists(tasks)
        task_map = {t.id: t for t in tasks}

        impacts: dict[str, dict[str, Any]] = {}
        for t in tasks:
            blockers = blocked_by.get(t.id, [])
            direct_blocked_count = len(blockers)
            transitive_count = 0
            visited = set(blockers)
            queue = deque(blockers)
            while queue:
                bid = queue.popleft()
                sub_blocked = blocked_by.get(bid, [])
                for sb in sub_blocked:
                    if sb not in visited:
                        visited.add(sb)
                        queue.append(sb)
                        transitive_count += 1

            total_impact = direct_blocked_count + transitive_count
            score = min(100.0, total_impact * 25)

            blocking_task_names = []
            for bid in blockers:
                bt = task_map.get(bid)
                if bt:
                    blocking_task_names.append(bt.title)

            blocked_by_ids = t.dependencies or []
            blocked_by_names = []
            for bid in blocked_by_ids:
                bt = task_map.get(bid)
                if bt:
                    blocked_by_names.append(bt.title)

            impacts[t.id] = {
                "task_id": t.id,
                "title": t.title,
                "blocks_directly": direct_blocked_count,
                "blocks_transitively": transitive_count,
                "total_impact_score": round(score, 1),
                "blocked_by_ids": blocked_by_ids,
                "blocked_by_names": blocked_by_names,
                "blocking_ids": blockers,
                "blocking_names": blocking_task_names,
            }

        return impacts

    @staticmethod
    def find_highest_leverage_tasks(
        tasks: list[Task], top_n: int = 3
    ) -> list[dict[str, Any]]:
        impacts = DependencyAnalyzer.compute_blocking_impact(tasks)
        open_tasks = [t for t in tasks if t.status != "done"]
        scored = []
        for t in open_tasks:
            imp = impacts.get(t.id, {})
            leverage_score = imp.get("total_impact_score", 0)
            if t.priority in ("P0", "P1"):
                leverage_score += 20
            if t.vp_escalation:
                leverage_score += 15
            scored.append(
                {
                    "task_id": t.id,
                    "title": t.title,
                    "leverage_score": round(leverage_score, 1),
                    "blocks_directly": imp.get("blocks_directly", 0),
                    "blocks_transitively": imp.get("blocks_transitively", 0),
                    "blocked_by": imp.get("blocked_by_names", []),
                }
            )

        scored.sort(key=lambda x: x["leverage_score"], reverse=True)
        return scored[:top_n]

    @staticmethod
    def get_unblocking_recommendations(tasks: list[Task]) -> list[dict[str, Any]]:
        impacts = DependencyAnalyzer.compute_blocking_impact(tasks)
        task_map = {t.id: t for t in tasks}
        recommendations = []

        for t in tasks:
            if t.status == "blocked" and t.dependencies:
                for dep_id in t.dependencies:
                    dep_task = task_map.get(dep_id)
                    if dep_task:
                        recommendations.append(
                            {
                                "blocked_task_id": t.id,
                                "blocked_task_title": t.title,
                                "blocking_task_id": dep_id,
                                "blocking_task_title": dep_task.title,
                                "blocking_task_status": dep_task.status,
                                "suggestion": f"Unblock '{t.title}' by completing/resolving '{dep_task.title}'",
                            }
                        )

        critical_path = DependencyAnalyzer.find_critical_path(tasks)
        if len(critical_path) >= 2:
            last_title = (
                task_map[critical_path[-1]].title
                if critical_path[-1] in task_map
                else critical_path[-1]
            )
            first_title = (
                task_map[critical_path[0]].title
                if critical_path[0] in task_map
                else critical_path[0]
            )
            recommendations.append(
                {
                    "blocked_task_id": critical_path[-1],
                    "blocked_task_title": last_title,
                    "blocking_task_id": critical_path[0],
                    "blocking_task_title": first_title,
                    "blocking_task_status": "open",
                    "suggestion": f"Critical path: start with '{first_title}' to unlock downstream tasks",
                }
            )

        return recommendations
