import asyncio
import yaml
from pathlib import Path
from ct1.core.orchestrator import Orchestrator
from ct1.cli.display import (console, print_banner, print_framing, print_round_header,
                               print_mind_response, print_tension, print_convergence,
                               print_final_response, print_journal_note, print_error)
from ct1.cli.commands import cmd_journal, cmd_status, cmd_train

async def run_interactive(config_path: str = "ct1/server/model_config.yaml"):
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    print_banner()

    console.print("[dim]Loading orchestrator...[/]")
    try:
        orch = Orchestrator(config_path)
    except Exception as e:
        print_error(f"Failed to load orchestrator: {e}")
        return

    journal_dir = cfg["journal"]["path"]
    console.print("[green]Ready.[/] Commands: /journal [stats], /status, /train, /auto <goal>, /quit\n")

    try:
        while True:
            try:
                raw = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not raw:
                continue

            if raw in ("/quit", "/exit"):
                break
            elif raw.startswith("/journal"):
                await cmd_journal(raw[8:].strip(), journal_dir)
            elif raw.startswith("/status"):
                await cmd_status(orch)
            elif raw.startswith("/train"):
                await cmd_train(orch)
            elif raw.startswith("/auto"):
                goal = raw[5:].strip()
                if goal:
                    from ct1.cli.autonomous import run_autonomous
                    await run_autonomous(orch, goal)
                else:
                    print_error("Usage: /auto <goal>")
            else:
                await _run_deliberation(orch, raw)

    finally:
        await orch.close()
        console.print("[dim]Goodbye.[/]")

async def _run_deliberation(orch: Orchestrator, goal: str):
    """Run deliberation with live display."""
    console.print()
    result = await orch.think(goal)
    print_final_response(result["response"])
    reflection = result.get("reflection", {})
    lesson = reflection.get("lesson", "")
    score = reflection.get("self_score", 0.5)
    if lesson and lesson != "reflection parse failed":
        print_journal_note(score, lesson)
    console.print()
