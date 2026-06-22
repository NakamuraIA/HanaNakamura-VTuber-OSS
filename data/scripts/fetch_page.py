import urllib.request
import sys

url = sys.argv[1] if len(sys.argv) > 1 else "https://guns.lol/sunnyvio"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
resp = urllib.request.urlopen(req, timeout=10)
html = resp.read().decode("utf-8", "replace")
print(html[:8000])
