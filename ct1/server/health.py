import httpx
import asyncio
import time

async def check_server_health(base_url: str = "http://localhost:8080") -> dict:
    """Check if llama-server is alive and responding."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base_url}/health")
            if r.status_code == 200:
                return {"alive": True, "url": base_url, "status": r.json()}
            return {"alive": False, "url": base_url, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"alive": False, "url": base_url, "error": str(e)}

async def wait_for_server(base_url: str = "http://localhost:8080", timeout: int = 60) -> bool:
    """Poll until server is alive or timeout expires."""
    start = time.time()
    while time.time() - start < timeout:
        result = await check_server_health(base_url)
        if result["alive"]:
            return True
        await asyncio.sleep(2)
    return False
