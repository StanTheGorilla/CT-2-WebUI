import asyncio
import json
import time
from pathlib import Path
from ct1.core.orchestrator import Orchestrator
from ct1.cli.display import console

async def run_autonomous(
    orch: Orchestrator,
    goal: str,
    max_cycles: int = 50,
    token_budget: int = 32000,
    log_dir: str = "ct1/data/logs"
):
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    log_path = Path(log_dir) / f"auto_{timestamp}.jsonl"

    console.print(f"[bold yellow][AUTO][/] Goal: {goal}")
    console.print(f"[dim]Log: {log_path} | Press Ctrl+C to stop[/]\n")

    # Brain generates a plan
    plan_result = await orch.think(
        f"Autonomous session goal: {goal}\n\n"
        f"List 3-7 concrete numbered subtasks to accomplish this goal. "
        f"Output the numbered list only, one per line."
    )
    plan_text = plan_result["response"]
    console.print(f"[yellow][plan][/]\n{plan_text}\n")

    # Parse subtasks from numbered list
    lines = [l.strip() for l in plan_text.split("\n") if l.strip()]
    subtasks = []
    for l in lines:
        if l and l[0].isdigit():
            parts = l.split(".", 1)
            if len(parts) > 1:
                subtasks.append(parts[1].strip())
    if not subtasks:
        subtasks = [goal]

    results = []
    scores = []
    tokens_used = 0

    try:
        for i, subtask in enumerate(subtasks, 1):
            if tokens_used > token_budget:
                console.print(f"[yellow][auto] Token budget reached after {i-1} subtasks.[/]")
                break

            console.print(f"[dim][{i}/{len(subtasks)}][/] {subtask}")

            try:
                result = await orch.think(subtask)
            except Exception as e:
                console.print(f"[red][error] {e}[/]")
                continue

            score = result["reflection"].get("self_score", 0.5)
            scores.append(score)
            entry = {"subtask": subtask, "response": result["response"], "score": score}
            results.append(entry)

            tokens_used += len(result["response"]) // 4 + 500

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            preview = result["response"][:120] + "..." if len(result["response"]) > 120 else result["response"]
            console.print(f"  [dim]score={score:.2f}[/] {preview}\n")

            # Plateau detection: last 5 scores within 0.05 range
            if len(scores) >= 5 and (max(scores[-5:]) - min(scores[-5:])) < 0.05:
                console.print("[yellow][auto] Score plateau detected. Stopping.[/]")
                break

    except KeyboardInterrupt:
        console.print("\n[yellow][auto] Interrupted.[/]")

    avg_score = sum(scores) / len(scores) if scores else 0
    console.print(f"\n[bold yellow][DONE][/] {len(results)}/{len(subtasks)} subtasks | avg score: {avg_score:.2f}")
    console.print(f"[dim]Log: {log_path}[/]")
    return results
