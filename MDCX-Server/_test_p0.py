"""P0 核心功能测试脚本"""
import asyncio
import httpx

BASE = "http://127.0.0.1:8420/api/v1"
results = {"pass": 0, "fail": 0, "errors": []}

def check(name, ok, detail=""):
    if ok:
        results["pass"] += 1
        print(f"  [PASS] {name}")
    else:
        results["fail"] += 1
        results["errors"].append(f"{name}: {detail}")
        print(f"  [FAIL] {name} - {detail}")

async def test():
    async with httpx.AsyncClient() as c:
        # Wait for server
        print("Waiting for server...")
        for i in range(15):
            try:
                r = await c.get(f"{BASE}/health")
                if r.status_code in (200, 404):
                    break
            except:
                pass
            await asyncio.sleep(1)
        print(f"Server ready after {i+1}s")

        # P0-1: Health check
        r = await c.get(f"{BASE}/health")
        check("P0-1-1 Health check", r.status_code in (200, 404))

        # P0-2: Modules list
        r = await c.get(f"{BASE}/modules")
        d = r.json()
        check("P0-2-1 GET /modules status", r.status_code == 200)
        check("P0-2-2 GET /modules has 5 modules", len(d) == 5, f"got {len(d)}")
        check("P0-2-3 GET /modules has chinese", any(m["name"] == "chinese" for m in d))
        check("P0-2-4 GET /modules has fc2", any(m["name"] == "fc2" for m in d))
        check("P0-2-5 GET /modules has uncensored", any(m["name"] == "uncensored" for m in d))
        check("P0-2-6 GET /modules has pornhub", any(m["name"] == "pornhub" for m in d))

        # P0-2: Modules config
        r = await c.get(f"{BASE}/modules/config")
        d = r.json()
        check("P0-2-7 GET /modules/config status", r.status_code == 200)
        check("P0-2-8 config has chinese", "chinese" in d)

        # P0-3: Scan module (chinese - no media dirs)
        r = await c.post(f"{BASE}/modules/chinese/scan")
        check("P0-3-1 scan no media dirs", r.status_code == 400, str(r.json()))
        check("P0-3-2 scan returns proper error", "未配置媒体目录" in str(r.json()))

        # P0-4: Chinese movies/actors (empty DB)
        r = await c.get(f"{BASE}/chinese/movies")
        d = r.json()
        check("P0-4-1 GET /chinese/movies status", r.status_code == 200)
        if isinstance(d, dict):
            check("P0-4-2 chinese movies has total", "total" in d)

        r = await c.get(f"{BASE}/chinese/actors")
        check("P0-4-3 GET /chinese/actors status", r.status_code == 200)

        # P0-4: FC2 movies/actors
        r = await c.get(f"{BASE}/fc2/movies")
        d = r.json()
        check("P0-4-4 GET /fc2/movies status", r.status_code == 200)
        if isinstance(d, dict):
            check("P0-4-5 fc2 movies has total", "total" in d)

        r = await c.get(f"{BASE}/fc2/actors")
        check("P0-4-6 GET /fc2/actors status", r.status_code == 200)

        # P0-4: Uncensored movies/actors
        r = await c.get(f"{BASE}/uncensored/movies")
        check("P0-4-7 GET /uncensored/movies status", r.status_code == 200)
        r = await c.get(f"{BASE}/uncensored/actors")
        check("P0-4-8 GET /uncensored/actors status", r.status_code == 200)

        # P0-4: Pornhub movies/actors
        r = await c.get(f"{BASE}/pornhub/movies")
        check("P0-4-9 GET /pornhub/movies status", r.status_code == 200)
        r = await c.get(f"{BASE}/pornhub/actors")
        check("P0-4-10 GET /pornhub/actors status", r.status_code == 200)

        # P0-5: Unified movies
        r = await c.get(f"{BASE}/modules/unified/movies")
        d = r.json()
        check("P0-5-1 unified movies status", r.status_code == 200)
        check("P0-5-2 unified movies has total", "total" in d)
        check("P0-5-3 unified movies has items", "items" in d)

        # P0-5: Unified movies filtered by module
        r = await c.get(f"{BASE}/modules/unified/movies", params={"module_name": "chinese"})
        check("P0-5-4 unified movies filter chinese", r.status_code == 200)

        # P0-6: Unified search
        r = await c.get(f"{BASE}/modules/unified/search", params={"keyword": "test"})
        d = r.json()
        check("P0-6-1 unified search status", r.status_code == 200)
        check("P0-6-2 unified search has items", "items" in d)

        # P0-2: Module stats
        r = await c.get(f"{BASE}/modules/chinese/stats")
        check("P0-2-9 GET /modules/chinese/stats status", r.status_code == 200)

        # P0-3: Module toggle
        r = await c.patch(f"{BASE}/modules/chinese/toggle", params={"enabled": False})
        check("P0-3-3 toggle chinese disabled", r.status_code == 200)
        r = await c.patch(f"{BASE}/modules/chinese/toggle", params={"enabled": True})
        check("P0-3-4 toggle chinese enabled", r.status_code == 200)

        # P0-3: Config update
        r = await c.put(f"{BASE}/modules/config", json={"chinese": {"enabled": True}})
        check("P0-3-5 update config", r.status_code == 200, str(r.json()))

        # Dashboard stats
        r = await c.get(f"{BASE}/stats/dashboard")
        d = r.json()
        check("P0-1-2 Dashboard stats status", r.status_code == 200)
        check("P0-1-3 Dashboard has modules", "modules" in d, str(list(d.keys())))
        if "modules" in d:
            check("P0-1-4 Dashboard modules has chinese", "chinese" in d["modules"])
            check("P0-1-5 Dashboard modules has fc2", "fc2" in d["modules"])

    # Summary
    print(f"\n{'='*50}")
    print(f"总结果: {results['pass'] + results['fail']} 项")
    print(f"PASS: {results['pass']} 项")
    print(f"FAIL: {results['fail']} 项")
    if results["errors"]:
        print("\n失败项:")
        for e in results["errors"]:
            print(f"  - {e}")
    return results

if __name__ == "__main__":
    r = asyncio.run(test())
    exit(0 if r["fail"] == 0 else 1)
