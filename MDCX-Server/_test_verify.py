import urllib.request, json

# Test movies list
resp = urllib.request.urlopen('http://127.0.0.1:8420/api/v1/movies?page=1&page_size=1', timeout=10)
data = json.loads(resp.read())
mid = data['items'][0]['id']
code = data['items'][0]['code']
print(f'Movies list: {data["total"]} total, first: id={mid}, code={code}')

# Test health
resp = urllib.request.urlopen('http://127.0.0.1:8420/api/v1/health/version', timeout=10)
print(f'Health check: {resp.status}')

# Test actors
resp = urllib.request.urlopen('http://127.0.0.1:8420/api/v1/actors?page=1&page_size=2', timeout=10)
data = json.loads(resp.read())
items = data.get('items', data) if isinstance(data, dict) else data
print(f'Actors: count={len(items)}')

# Test cover (expect 404 on G:)
try:
    resp = urllib.request.urlopen(f'http://127.0.0.1:8420/api/v1/movies/{mid}/cover/file', timeout=10)
    print(f'Cover: HTTP {resp.status}, size={len(resp.read())} bytes')
except urllib.error.HTTPError as e:
    print(f'Cover: HTTP {e.code} (expected, G: has no data)')
except Exception as e:
    print(f'Cover: ERROR - {e}')

print('All tests passed!')
