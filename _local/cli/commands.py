import asyncio
from ct1.memory.journal_reader import JournalReader
from ct1.cli.display import console

async def cmd_journal(args: str, journal_dir: str):
    reader = JournalReader(journal_dir)
    if "stats" in args:
        stats = reader.get_stats()
        console.print(f"[bold]Total:[/] {stats['total']}")
        console.print(f"[bold]Avg score:[/] {stats.get('avg_self_score', 'n/a')}")
        console.print(f"[bold]Avg rounds:[/] {stats.get('avg_rounds', 'n/a')}")
        console.print(f"[bold]Mind usefulness:[/] {stats.get('mind_useful_counts', {})}")
    else:
        entries = reader.journal.read_recent(5)
        if not entries:
            console.print("[dim]No journal entries yet.[/]")
            return
        for e in entries:
            console.print(f"[dim]Goal:[/] {str(e.get('goal', '?'))[:60]}")
            console.print(f"[dim]Lesson:[/] {e.get('lesson', '?')}")
            console.print(f"[dim]Score:[/] {e.get('self_score', '?')}\n")

async def cmd_status(orchestrator):
    from ct1.server.health import check_server_health
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load(Path("ct1/server/model_config.yaml").read_text(encoding="utf-8"))
    port = cfg["llama_server"]["port"]
    health = await check_server_health(f"http://localhost:{port}")
    journal_count = orchestrator.journal.count()
    status = "[green]ONLINE[/]" if health["alive"] else "[red]OFFLINE[/]"
    console.print(f"[bold]Server:[/] {status}")
    console.print(f"[bold]Journal entries:[/] {journal_count}")
    console.print(f"[bold]Brain lessons loaded:[/] {len(orchestrator.brain.lessons)}")

async def cmd_train(orchestrator):
    min_entries = 100
    journal_count = orchestrator.journal.count()
    if journal_count < min_entries:
        console.print(f"[yellow]Need {min_entries} journal entries to train. Have {journal_count}.[/]")
        return
    console.print("[yellow]Starting LoRA training... (this will take a while)[/]")
    from ct1.evolution.lora_trainer import trigger_training
    from ct1.evolution.preference_extractor import PreferenceExtractor
    extractor = PreferenceExtractor()
    n = extractor.save_dataset()
    console.print(f"[dim]Extracted {n} preference pairs.[/]")
    await trigger_training()
