"""Capture local UI screenshots into screenshots/ using Chrome DevTools."""
from __future__ import annotations

import base64
import json
import subprocess
import time
from pathlib import Path

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "screenshots"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
BROWSER = CHROME if CHROME.exists() else EDGE
PORT = 9222
BASE = "http://127.0.0.1:8000"
EMAIL = "admin@example.com"
PASSWORD = "change-me-admin-password"


def wait_devtools() -> dict:
    for _ in range(50):
        try:
            tabs = httpx.get(f"http://127.0.0.1:{PORT}/json/list", timeout=1).json()
            if tabs:
                return tabs[0]
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError("DevTools did not start")


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0

    def send(self, method: str, params: dict | None = None, session_id: str | None = None) -> dict:
        self._id += 1
        payload = {"id": self._id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        self.ws.send(json.dumps(payload))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == payload["id"]:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result") or {}


def screenshot(cdp: CDP, session_id: str, name: str) -> None:
    result = cdp.send("Page.captureScreenshot", {"format": "png", "fromSurface": True}, session_id)
    (OUT / name).write_bytes(base64.b64decode(result["data"]))
    print("saved", OUT / name)


def login_session() -> tuple[str, str]:
    with httpx.Client(follow_redirects=True) as client:
        client.post(f"{BASE}/login", data={"email": EMAIL, "password": PASSWORD})
        cookie = client.cookies.get("dis360_session")
        if not cookie:
            raise RuntimeError("Login did not set session cookie")
        chat = client.post(f"{BASE}/chat/new")
        return cookie, str(chat.url)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    cookie, chat_url = login_session()
    profile = ROOT / ".chrome-shot"
    profile.mkdir(exist_ok=True)
    proc = subprocess.Popen(
        [
            str(BROWSER),
            f"--remote-debugging-port={PORT}",
            f"--user-data-dir={profile}",
            "--headless=new",
            "--disable-gpu",
            "--window-size=1440,900",
            "--hide-scrollbars",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1.0)
        tab = wait_devtools()
        with connect(tab["webSocketDebuggerUrl"], max_size=20_000_000) as ws:
            cdp = CDP(ws)
            target = cdp.send("Target.createTarget", {"url": "about:blank"})
            attached = cdp.send("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True})
            sid = attached["sessionId"]
            cdp.send("Page.enable", session_id=sid)
            cdp.send("Network.enable", session_id=sid)
            cdp.send(
                "Network.setCookie",
                {"name": "dis360_session", "value": cookie, "url": BASE},
                sid,
            )

            def open_url(url: str, wait: float = 2.0) -> None:
                cdp.send("Page.navigate", {"url": url}, sid)
                time.sleep(wait)

            open_url(f"{BASE}/")
            screenshot(cdp, sid, "01-landing.png")
            open_url(f"{BASE}/dashboard")
            screenshot(cdp, sid, "02-dashboard.png")
            open_url(chat_url)
            screenshot(cdp, sid, "03-chat.png")

            csv_path = ROOT / "examples" / "sample_sales.csv"
            with httpx.Client(cookies={"dis360_session": cookie}, follow_redirects=True) as client:
                with csv_path.open("rb") as handle:
                    result = client.post(
                        f"{BASE}/analyze",
                        data={"chart_type": "pie", "x_column": "region", "y_column": "revenue", "analyst_mode": "business"},
                        files={"data_file": ("sample_sales.csv", handle, "text/csv")},
                    )
                result_html = ROOT / ".chrome-shot" / "result.html"
                result_html.write_text(result.text, encoding="utf-8")
            # Result is a 200 HTML page; reopen via cookie by storing last analysis is hard.
            # Navigate using data URL is too big. Post again in-browser is harder.
            # Open dashboard files list is enough; also screenshot analyze by fetching Location-less page:
            # Save to a temp route... Use Page.setDocumentContent? Simpler: write file and open through the app host.
            (ROOT / "storage" / "outputs" / "_shot_result.html").write_text(result.text, encoding="utf-8")
            open_url(f"{BASE}/outputs/_shot_result.html", wait=2.2)
            screenshot(cdp, sid, "04-analysis.png")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
