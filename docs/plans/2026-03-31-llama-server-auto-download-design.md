# llama-server Auto-Download — Design

**Date:** 2026-03-31

## Goal

When `python -m ct1.server.api` starts and `llama-server` is not found, automatically download both Vulkan and CUDA builds from the latest llama.cpp GitHub release into `bin/`. User picks the active backend via a Settings UI dropdown.

## Auto-Download Flow

Triggered inside `_find_llama_executable` when no binary is found anywhere. Steps:

1. Hit `https://api.github.com/repos/ggerganov/llama.cpp/releases/latest` to get the latest release tag and asset list
2. Filter assets for the current platform (Windows/Linux/macOS)
3. Download both backends in sequence, printing progress to terminal: `[download] llama-server (Vulkan) 45%...`
4. Extract each zip into `bin/vulkan/` and `bin/cuda/` at the project root
5. Return the path to the active backend's `llama-server` executable

If `bin/` already exists with both backends, skip download entirely.

## Download Targets by Platform

| Platform | Vulkan asset | CUDA asset |
|----------|-------------|------------|
| Windows | `llama-*-bin-win-vulkan-x64.zip` | `llama-*-bin-win-cuda-cu12.4-x64.zip` |
| Linux | `llama-*-bin-ubuntu-x64.zip` | `llama-*-bin-ubuntu-x64-cuda-cu12.4.zip` |
| macOS | `llama-*-bin-macos-arm64.zip` | *(none — Metal built-in)* |

## Download Location

```
bin/
  vulkan/    # extracted Vulkan build — gitignored
  cuda/      # extracted CUDA build — gitignored (Windows/Linux only)
```

Add `bin/` to `.gitignore`.

## `model_config.yaml` — New Field

```yaml
backend: vulkan   # vulkan | cuda  (macOS ignores this — always uses Metal build)
```

Default: `vulkan`.

## Settings UI

Add a **Backend** dropdown to the existing Settings page, below the model selector. Options: `Vulkan` / `CUDA` (macOS shows neither — Metal only). Changing backend:
1. Writes `backend` field to `model_config.yaml`
2. Restarts llama-server with the new executable (same flow as model change)

## `launcher.py` Changes

- `_find_llama_executable`: add `bin/vulkan/` and `bin/cuda/` to the search path based on `backend` config field; call `download_llama_server()` as last resort before raising `FileNotFoundError`
- New `download_llama_server(project_root, backend_config)`: GitHub API fetch → asset filtering → download with progress → zip extraction

## `.gitignore` Addition

```
bin/
```
