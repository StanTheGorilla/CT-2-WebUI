from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

MIND_COLORS = {"alpha": "cyan", "beta": "green", "gamma": "magenta", "brain": "yellow"}
MIND_LABELS = {"alpha": "α", "beta": "β", "gamma": "γ"}

def print_banner():
    console.print(Panel(
        "[bold yellow]CT-1[/] — Consciousness Testbed v0.2\n"
        "[dim]Brain + 3 Minds | Reasoning-Distilled | Vulkan[/]",
        border_style="yellow"
    ))

def print_framing(framed: str, complexity: str = ""):
    complexity_tag = f" [dim](complexity: {complexity})[/]" if complexity else ""
    console.print(f"[dim yellow][brain][/] {framed}{complexity_tag}")

def print_round_header(round_num: int):
    console.print(f"\n[dim]  ── round {round_num} ──[/]")

def print_mind_response(name: str, response, verbose: bool = False):
    """Display mind response. response is {reasoning, conclusion} dict or string."""
    color = MIND_COLORS.get(name, "white")
    label = MIND_LABELS.get(name, name)
    if isinstance(response, dict):
        conclusion = response.get("conclusion", "")
        reasoning = response.get("reasoning", "")
    else:
        conclusion = str(response)
        reasoning = ""

    if verbose and reasoning:
        # Show reasoning in dim italic, then conclusion
        for line in reasoning.split("\n"):
            console.print(f"  [dim {color}]  {line}[/]")
        console.print(f"  [bold {color}][{label}][/] {conclusion}")
    else:
        console.print(f"  [bold {color}][{label}][/] {conclusion}")

def print_tension(description: str):
    console.print(f"\n  [bold red][tension][/] [italic]{description}[/]")

def print_convergence(confidence: float, strongest: str = ""):
    strongest_tag = f" | strongest: {strongest}" if strongest else ""
    console.print(f"\n  [bold yellow][brain][/] [dim]converging... confidence {confidence:.2f}{strongest_tag}[/]")

def print_final_response(response: str):
    console.print(Panel(
        Text(response, style="bold white"),
        title="[bold yellow]CT-1[/]",
        border_style="yellow",
        padding=(1, 2)
    ))

def print_journal_note(score: float, lesson: str):
    short = lesson[:80] + "..." if len(lesson) > 80 else lesson
    console.print(f"[dim]  [journal] score={score:.1f} | {short}[/]")

def print_status(server_alive: bool, journal_count: int):
    status = "[green]ONLINE[/]" if server_alive else "[red]OFFLINE[/]"
    console.print(f"[bold]Server:[/] {status}")
    console.print(f"[bold]Journal entries:[/] {journal_count}")

def print_error(msg: str):
    console.print(f"[bold red][error][/] {msg}")
