"""s3_sync.delete_one sends one DeleteObject signed in its headers, path
style, for the store's bucket and prefix; an object already gone (404) is
not an error, and a refusal (403) is. Against a local HTTP server, no
credentials needed. Run from the repository root:
  python tests/s3_sync_delete.py
Needs obstore and boto3.
"""
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "py")

seen = []
ERR = '<?xml version="1.0" encoding="UTF-8"?><Error><Code>{}</Code><Message>m</Message></Error>'


class Handler(BaseHTTPRequestHandler):
    def do_DELETE(self):
        seen.append((self.command, self.path, dict(self.headers)))
        name = self.path.rsplit("/", 1)[-1].split("?")[0]
        code, body = {"gone": (404, ERR.format("NoSuchKey")),
                      "denied": (403, ERR.format("AccessDenied"))}.get(name, (204, ""))
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update({"AWS_S3_ENDPOINT": f"127.0.0.1:{srv.server_port}", "AWS_HTTPS": "NO",
                   "AWS_VIRTUAL_HOSTING": "FALSE", "AWS_REGION": "us-west-2",
                   "AWS_ACCESS_KEY_ID": "AKIDTEST", "AWS_SECRET_ACCESS_KEY": "secret",
                   "AWS_SESSION_TOKEN": "token"})
from s3_sync import delete_one, store_for  # noqa: E402

store, _ = store_for("/vsis3/ausantarctic/ausantarctic-scratch/t")
delete_one(store, "a/b.txt")
method, path, headers = seen[-1]
u = urllib.parse.urlsplit(path)
assert method == "DELETE", method
assert u.path == "/ausantarctic/ausantarctic-scratch/t/a/b.txt", u.path
assert headers.get("Authorization", "").startswith("AWS4-HMAC-SHA256 "), headers.get("Authorization")
assert "X-Amz-Signature" not in u.query, u.query
assert headers.get("X-Amz-Security-Token") == "token"
assert len(seen) == 1, seen

delete_one(store, "gone")  # already gone: no error
try:
    delete_one(store, "denied")
except RuntimeError as e:
    assert "AccessDenied" in str(e), e
else:
    raise AssertionError("a refused DELETE passed silently")
srv.shutdown()
print("PASS tests/s3_sync_delete.py")
