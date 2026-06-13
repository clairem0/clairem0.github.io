#!/usr/bin/env python3
"""Local-only editable homepage server.

The published site stays clean: edit controls are injected only into localhost
responses and are never written into index.html.
"""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "index.html"
MAX_BODY_BYTES = 1_000_000
HOST = "127.0.0.1"
DEFAULT_PORT = 8791

CONTENT_START = '<main id="site-content">'
CONTENT_END = "\n</main>"
EDITOR_MARKERS = (
    "contenteditable=",
    "__save_homepage",
    "local-edit-toolbar",
    "local-edit-toast",
    "local-edit-style",
    "data-local-editor",
)

EDITOR_STYLE = """
  <style id="local-edit-style">
    body[data-local-editor="true"] {
      padding-bottom: 96px;
    }
    body[data-local-editor="true"] #site-content[contenteditable] *:hover {
      outline: 1px dashed var(--accent-light);
      outline-offset: 2px;
      border-radius: 2px;
    }
    body[data-local-editor="true"] #site-content[contenteditable] *:focus {
      outline: 1px solid var(--accent);
      outline-offset: 2px;
      border-radius: 2px;
    }
    body[data-local-editor="true"] .card-detail {
      max-height: none;
    }
    body[data-local-editor="true"] .card-arrow {
      transform: rotate(90deg);
    }
    #local-edit-toolbar {
      position: fixed;
      right: 20px;
      bottom: 20px;
      z-index: 1000;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: rgba(255, 253, 248, 0.96);
      box-shadow: 0 6px 24px rgba(44, 36, 28, 0.16);
      font-family: 'DM Sans', sans-serif;
    }
    #local-edit-toolbar button,
    #local-edit-toolbar a {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #fff;
      color: var(--warm-dark);
      cursor: pointer;
      font: inherit;
      font-size: 12px;
      font-weight: 600;
      line-height: 1;
      text-decoration: none;
    }
    #local-edit-toolbar .btn-save {
      border-color: var(--warm-dark);
      background: var(--warm-dark);
      color: #fff;
    }
    #local-edit-status {
      min-width: 92px;
      color: var(--warm-mid);
      font-size: 12px;
      text-align: right;
    }
    #local-edit-toast {
      position: fixed;
      right: 20px;
      bottom: 82px;
      z-index: 1001;
      padding: 10px 14px;
      border-radius: 6px;
      background: var(--warm-dark);
      color: #fff;
      font-family: 'DM Sans', sans-serif;
      font-size: 12px;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s;
    }
    #local-edit-toast.show {
      opacity: 1;
    }
    @media print {
      #local-edit-toolbar,
      #local-edit-toast {
        display: none;
      }
      body[data-local-editor="true"] #site-content[contenteditable] *:hover,
      body[data-local-editor="true"] #site-content[contenteditable] *:focus {
        outline: none;
      }
    }
  </style>
"""

EDITOR_CHROME = """
<div id="local-edit-toolbar">
  <span id="local-edit-status">Ready</span>
  <a href="/__preview" target="_blank">Preview</a>
  <button type="button" id="local-edit-reload">Reload</button>
  <button type="button" id="local-edit-save" class="btn-save">Save edits</button>
</div>
<div id="local-edit-toast"></div>
<script>
(function () {
  const content = document.getElementById('site-content');
  const saveButton = document.getElementById('local-edit-save');
  const reloadButton = document.getElementById('local-edit-reload');
  const status = document.getElementById('local-edit-status');
  const toast = document.getElementById('local-edit-toast');

  document.querySelectorAll('.card').forEach((card) => {
    card.onclick = null;
  });

  document.addEventListener('click', (event) => {
    if (event.target.closest('#local-edit-toolbar')) return;
    if (event.target.closest('#site-content a')) {
      event.preventDefault();
    }
  }, true);

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 1800);
  }

  async function saveEdits() {
    const clone = content.cloneNode(true);
    clone.removeAttribute('contenteditable');
    clone.removeAttribute('spellcheck');
    clone.querySelectorAll('.card.expanded').forEach((card) => {
      card.classList.remove('expanded');
    });

    status.textContent = 'Saving...';
    try {
      const response = await fetch('/__save_homepage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: window.location.pathname,
          contentHtml: clone.innerHTML
        })
      });

      if (!response.ok) {
        throw new Error(await response.text());
      }

      status.textContent = 'Saved';
      showToast('Saved edits');
    } catch (error) {
      console.error(error);
      status.textContent = 'Save failed';
      showToast('Save failed');
    }
  }

  saveButton.addEventListener('click', saveEdits);
  reloadButton.addEventListener('click', () => window.location.reload());
  window.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      saveEdits();
    }
  });
})();
</script>
"""


class HomepageEditHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        request_path = self.path.split("?", 1)[0]
        if request_path in ("/", "/index.html"):
            self._send_html(self._editable_index_html())
            return
        if request_path == "/__preview":
            self._send_html(INDEX_FILE.read_text(encoding="utf-8"))
            return
        super().do_GET()

    def do_POST(self):
        request_path = self.path.split("?", 1)[0]
        if request_path != "/__save_homepage":
            self.send_error(404, "Unknown endpoint")
            return

        try:
            payload = self._read_payload()
            self._validate_save_path(payload.get("path"))
            self._write_content_html(payload["contentHtml"])
        except Exception as exc:  # Keep browser editing feedback useful.
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "path": str(INDEX_FILE)}).encode("utf-8"))

    def _send_html(self, body):
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _editable_index_html(self):
        html = INDEX_FILE.read_text(encoding="utf-8")
        html = html.replace(
            CONTENT_START,
            '<main id="site-content" contenteditable="true" spellcheck="true">',
            1,
        )
        html = html.replace("<body>", '<body data-local-editor="true">', 1)
        html = html.replace("</head>", f"{EDITOR_STYLE}</head>", 1)
        html = html.replace("</body>", f"{EDITOR_CHROME}</body>", 1)
        return html

    def _read_payload(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("Invalid save payload size")

        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _validate_save_path(self, request_path):
        if request_path not in ("/", "/index.html"):
            raise ValueError("Save path must be / or /index.html")

    def _write_content_html(self, content_html):
        if not isinstance(content_html, str) or not content_html.strip():
            raise ValueError("Missing homepage content")

        current = INDEX_FILE.read_text(encoding="utf-8")
        start = current.index(CONTENT_START) + len(CONTENT_START)
        end = current.index(CONTENT_END, start)
        updated = current[:start] + "\n" + content_html.strip() + "\n" + current[end:]
        INDEX_FILE.write_text(updated, encoding="utf-8")

    def log_message(self, fmt, *args):
        sys.stdout.write(fmt % args + "\n")
        sys.stdout.flush()


def check_publish_clean():
    html = INDEX_FILE.read_text(encoding="utf-8")
    missing = [marker for marker in (CONTENT_START, CONTENT_END) if marker not in html]
    leaked = [marker for marker in EDITOR_MARKERS if marker in html]

    if missing or leaked:
        if missing:
            print("Missing required marker(s): " + ", ".join(missing), file=sys.stderr)
        if leaked:
            print("Local editor artifact(s) found in index.html: " + ", ".join(leaked), file=sys.stderr)
        return 1

    print("index.html is clean for publish.")
    return 0


def main():
    if "--check-publish" in sys.argv:
        raise SystemExit(check_publish_clean())

    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadingHTTPServer((HOST, port), HomepageEditHandler)
    print(f"Serving editable homepage at http://{HOST}:{port}/")
    print("Press Ctrl-C to stop the server.")
    server.serve_forever()


if __name__ == "__main__":
    main()
