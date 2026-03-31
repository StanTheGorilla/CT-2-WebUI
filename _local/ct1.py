#!/usr/bin/env python3
"""
CT-1: Consciousness Testbed
Usage:
  python ct1.py                       # interactive CLI
  python ct1.py --auto "your goal"    # autonomous mode
  python ct1.py --start-server        # start llama-server only
"""
import asyncio
import argparse

def main():
    parser = argparse.ArgumentParser(
        description="CT-1 Consciousness Testbed — pseudo-AGI with 1 Brain + 3 Minds"
    )
    parser.add_argument("--auto", type=str, metavar="GOAL",
                        help="Run in autonomous mode with the given goal")
    parser.add_argument("--start-server", action="store_true",
                        help="Start llama-server (Vulkan) and wait")
    parser.add_argument("--config", type=str, default="ct1/server/model_config.yaml",
                        help="Path to model_config.yaml")
    args = parser.parse_args()

    if args.start_server:
        asyncio.run(_start_server(args.config))
    elif args.auto:
        asyncio.run(_run_auto(args.config, args.auto))
    else:
        asyncio.run(_run_interactive(args.config))

async def _start_server(config_path: str):
    from ct1.server.launcher import start_server, stop_server
    procs = await start_server(config_path)
    print("Servers running. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        stop_server(procs)

async def _run_interactive(config_path: str):
    from ct1.cli.interactive import run_interactive
    await run_interactive(config_path)

async def _run_auto(config_path: str, goal: str):
    from ct1.core.orchestrator import Orchestrator
    from ct1.cli.autonomous import run_autonomous
    orch = Orchestrator(config_path)
    try:
        await run_autonomous(orch, goal)
    finally:
        await orch.close()

if __name__ == "__main__":
    main()
