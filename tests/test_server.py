import pytest
import asyncio
from ct1.server.health import check_server_health, wait_for_server

@pytest.mark.asyncio
async def test_health_check_returns_false_when_server_down():
    result = await check_server_health("http://localhost:9999")
    assert result["alive"] == False
    assert "error" in result

@pytest.mark.asyncio
async def test_health_check_structure():
    result = await check_server_health("http://localhost:9999")
    assert "alive" in result
    assert "url" in result

from ct1.server.launcher import load_config, build_server_command

def test_build_server_command_includes_required_flags():
    cfg = load_config("ct1/server/model_config.yaml")
    cmd = build_server_command(cfg["llama_server"])
    cmd_str = " ".join(cmd)
    assert "llama-server" in cmd_str
    assert "--port" in cmd_str
    assert "--n-gpu-layers" in cmd_str
    assert "--parallel" in cmd_str
    assert "-c" in cmd_str

def test_load_config_has_expected_keys():
    cfg = load_config("ct1/server/model_config.yaml")
    assert "llama_server" in cfg
    assert "models" in cfg
