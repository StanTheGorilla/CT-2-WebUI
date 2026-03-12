from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

MIND_COLORS = {"alpha": "cyan", "beta": "green", "gamma": "magenta", "brain": "yellow"}
MIND_LABELS = {"alpha": "α", "beta": "β", "gamma": "γ"}

def print_banner():
    console.print(Panel(
        "[bold yellow]CT-1[/] — Consciousness Testbed v0.1\n"
        "[dim]Brain + 3 Minds | Qwen3.5-0.8B | Vulkan[/]",
        border_style="yellow"
    ))

def print_framing(framed: str):
    console.print(f"[dim yellow][brain][/] {framed}")

def print_round_header(round_num: int):
    console.print(f"\n[dim]  ── round {round_num} ──[/]")

def print_mind_response(name: str, response: str):
    color = MIND_COLORS.get(name, "white")
    label = MIND_LABELS.get(name, name)
    console.print(f"  [bold {color}][{label}][/] {response}")

def print_tension(description: str):
    console.print(f"\n  [bold red][tension][/] [italic]{description}[/]")

def print_convergence(confidence: float):
    console.print(f"\n  [bold yellow][brain][/] [dim]converging... confidence {confidence:.2f}[/]")

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
