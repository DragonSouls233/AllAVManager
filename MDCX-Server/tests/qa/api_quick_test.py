"""
API 快速测试 - 测试各模块 API 端点的基本情况
"""
import json
import urllib.request
import urllib.error

BASE_URL = "http://192.168.10.110:8420"
PASSWORD = "ACx36O1i9eHXkGdbaV4uDA"

# Login
data = json.dumps({"username": "admin", "password": PASSWORD}).encode()
req = urllib.request.Request(
    f"{BASE_URL}/api/v1/auth/login",
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=15) as resp:
    result = json.loads(resp.read().decode())
    token = result["access_token"]
    print(f"Token: {token[:40]}...")

headers = {"Authorization": f"Bearer {token}"}


def api(path):
    url = f"{BASE_URL}/api/v1/{path.lstrip('/')}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"ERROR": f"HTTP {e.code}", "detail": body[:200]}
    except Exception as e:
        return {"ERROR": str(e)}


# 1. Modules
print("\n=== 模块列表 ===")
mods = api("modules")
if isinstance(mods, list):
    for m in mods:
        print(f"  {m}")
elif isinstance(mods, dict):
    print(json.dumps(mods, ensure_ascii=False, indent=2)[:500])

# 2. JAV Actors
print("\n=== JAV演员列表 ===")
actors = api("jav/actors")
if isinstance(actors, list):
    items = actors
elif isinstance(actors, dict):
    if actors.get("ERROR"):
        print(f"  ERROR: {actors['ERROR']} - {actors.get('detail','')}")
        items = []
    else:
        items = actors.get("items", [])
else:
    items = []
if len(items) == 0:
    print("  [空列表] - 没有演员数据")
else:
    for a in items[:5]:
        print(f"  id={a.get('id')}, name={a.get('name')}, movies={a.get('movie_count')}, avatar={str(a.get('avatar_url',''))[:50]}")

# 3. JAV Movies
print("\n=== JAV影片列表(前5) ===")
movies = api("jav/movies?skip=0&limit=5")
items2 = movies.get("items", [])
print(f"  total={movies.get('total',0)}")
if items2:
    for m in items2[:3]:
        print(f"  id={m.get('id')}, code={m.get('code')}, title={str(m.get('title',''))[:40]}")
        print(f"    cover={str(m.get('cover_url',''))[:60]}")
        print(f"    file={str(m.get('file_path',''))[:60]}")
    # Detail of first movie
    mid = items2[0].get("id")
    print(f"\n=== 影片详情 id={mid} ===")
    md = api(f"jav/movies/{mid}")
    for k in ["code","title","release_date","cover_url","file_path","nfo_path","duration","status"]:
        v = md.get(k, "N/A")
        print(f"  {k}: {str(v)[:80]}")
else:
    print("  [空列表]")

# 4. Actor Detail (first actor)
print("\n=== 演员详情 ===")
if items:
    aid = items[0].get("id")
    ad = api(f"jav/actors/{aid}")
    if ad.get("ERROR"):
        print(f"  ERROR: {ad['ERROR']} - {ad.get('detail','')}")
    else:
        for k in ["id","name","nationality","avatar_url","movie_count","source","source_site"]:
            v = ad.get(k, "N/A")
            print(f"  {k}: {str(v)[:80]}")

# 5. Actress collection
print("\n=== 女优收藏 ===")
ac = api("actresses")
print(f"  {str(ac)[:500]}")

# 6. Stats dashboard
print("\n=== 仪表盘统计 ===")
stats = api("stats/dashboard")
print(f"  {str(stats)[:500]}")

# 7. Uncensored actors
print("\n=== JAV无码演员列表 ===")
unc = api("uncensored/actors")
print(f"  {str(unc)[:300]}")

# 8. FC2 actors
print("\n=== FC2演员列表 ===")
fc2 = api("fc2/actors")
print(f"  {str(fc2)[:300]}")

# 9. Pornhub actors
print("\n=== PORNHUB演员列表 ===")
ph = api("pornhub/actors")
print(f"  {str(ph)[:300]}")

# 10. Chinese actors
print("\n=== 国产演员列表 ===")
cn = api("chinese/actors")
print(f"  {str(cn)[:300]}")

# 11. Western actors
print("\n=== 欧美演员列表 ===")
west = api("western/actors")
print(f"  {str(west)[:300]}")

print("\n=== 测试完成 ===")
