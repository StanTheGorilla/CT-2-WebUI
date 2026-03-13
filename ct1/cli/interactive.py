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
    console.print("[green]Ready.[/] Commands: /journal [stats], /status, /train, /verbose, /auto <goal>, /quit")
    console.print("[dim]Tip: paste multi-line text freely — blank line submits.[/]\n")

    try:
        while True:
            try:
                raw = _read_multiline()
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
            elif raw == "/verbose":
                orch.verbose = not orch.verbose
                state = "ON" if orch.verbose else "OFF"
                console.print(f"[yellow]Verbose mode {state}[/] — {'showing' if orch.verbose else 'hiding'} reasoning traces")
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

def _read_multiline() -> str:
    """Collect lines until a blank line, then return joined text.
    Single-line: type message + Enter + Enter.
    Multi-line / paste: content ends naturally when a blank line is received.
    """
    lines = []
    while True:
        prompt = "> " if not lines else "... "
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            raise
        if line == "" and lines:
            break
        if line != "":
            lines.append(line)
    return "\n".join(lines).strip()


async def _run_deliberation(orch: Orchestrator, goal: str):
    """Run deliberation with live display."""
    console.print()

    def on_event(event: str, **data):
        if event == "framing":
            console.print("[dim yellow][brain][/] [dim]framing...[/]")
        elif event == "framed":
            print_framing(data["text"], data.get("complexity", ""))
        elif event == "round_start":
            print_round_header(data["round_num"])
        elif event == "mind_response":
            print_mind_response(data["name"], data["response"], verbose=orch.verbose)
        elif event == "tension":
            print_tension(data["description"])
            console.print(f"  [dim]followup → {data['followup']}[/]")
        elif event == "converging":
            print_convergence(data["confidence"], data.get("strongest", ""))
        elif event == "synthesizing":
            console.print(f"\n[dim yellow][brain][/] [dim]synthesizing...[/]")

    result = await orch.think(goal, on_event=on_event)
    console.print()
    print_final_response(result["response"])
    reflection = result.get("reflection", {})
    lesson = reflection.get("lesson", "")
    score = reflection.get("self_score", 0.5)
    if lesson and lesson != "reflection parse failed":
        print_journal_note(score, lesson)
    console.print()
