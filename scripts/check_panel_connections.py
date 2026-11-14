"""Read-only regression: an idle browser preconnection must not block the panel."""
import argparse,socket,time
from urllib.parse import urlsplit
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor
parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:18084');args=parser.parse_args()
url=urlsplit(args.url);start=time.monotonic()
with socket.create_connection((url.hostname,url.port or 80),timeout=3) as idle:
    time.sleep(.2)
    def get(_):
        with urlopen(args.url+'/',timeout=3) as response:
            assert response.status==200
            return len(response.read())
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert all(executor.map(get,range(8)))
print(f'PASS: idle connection and 8 concurrent requests, {time.monotonic()-start:.2f}s')
