"""Capture privacy-safe UI stills and real charts for the promo video."""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from websockets.sync.client import connect

PROJ = Path(__file__).resolve().parents[1]
ROOT = PROJ.parent
SHOT = PROJ / "capture" / "screenshots"
ASSETS = PROJ / "assets"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
BROWSER = CHROME if CHROME.exists() else EDGE
PORT = 9333
BASE = "http://127.0.0.1:8000"
EMAIL = "admin@example.com"
PASSWORD = "change-me-admin-password"

PRIVACY_JS = r"""
(() => {
  document.querySelectorAll('input[type="password"]').forEach((el) => {
    el.value = '';
    el.placeholder = '••••••••';
    el.removeAttribute('value');
  });
  document.querySelectorAll('small').forEach((el) => {
    if (/парол|admin@|демо-админ/i.test(el.textContent || '')) el.remove();
  });
  document.querySelectorAll('header span').forEach((el) => {
    if ((el.textContent || '').includes('@')) el.textContent = 'Кабинет';
  });
})();
"""


def wait_app() -> None:
    for _ in range(40):
        try:
            httpx.get(f"{BASE}/health", timeout=1)
            return
        except httpx.HTTPError:
            time.sleep(0.25)
    raise RuntimeError("App is not up on :8000")


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
    dest = SHOT / name
    dest.write_bytes(base64.b64decode(result["data"]))
    print("saved", dest)


def login_session() -> str:
    with httpx.Client(follow_redirects=True) as client:
        client.post(f"{BASE}/login", data={"email": EMAIL, "password": PASSWORD})
        cookie = client.cookies.get("dis360_session")
        if not cookie:
            raise RuntimeError("Login did not set session cookie")
        return cookie


def copy_chart(html_url: str, dest_name: str) -> str:
    name = Path(html_url).name
    src = ROOT / "storage" / "outputs" / name
    if src.exists():
        shutil.copy2(src, ASSETS / dest_name)
        return f"{BASE}/outputs/{name}"
    return ""


def main() -> None:
    SHOT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "app" / "static" / "dis-mascot.jpg", ASSETS / "dis-mascot.jpg")
    wait_app()

    sys.path.insert(0, str(ROOT))
    from app.config import settings
    from app.services import ChartService, FileService

    cfg = settings()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    analysis = FileService(cfg).analyze(ROOT / "examples" / "sample_sales.csv", "table", "business")
    (PROJ / "capture" / "extracted" / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    charts = ChartService(cfg)
    pie = charts.create(ROOT / "examples" / "sample_sales.csv", "pie", "region", "revenue")
    scatter = charts.create(ROOT / "examples" / "sample_sales.csv", "scatter", "orders", "revenue")
    pie_url = copy_chart(pie["html_url"], "chart-pie.html")
    scatter_url = copy_chart(scatter["html_url"], "chart-scatter.html")
    if pie.get("png_url"):
        png = ROOT / "storage" / "outputs" / Path(pie["png_url"]).name
        if png.exists():
            shutil.copy2(png, ASSETS / "chart-pie.png")
    if scatter.get("png_url"):
        png = ROOT / "storage" / "outputs" / Path(scatter["png_url"]).name
        if png.exists():
            shutil.copy2(png, ASSETS / "chart-scatter.png")
    print("charts", pie, scatter)

    cookie = login_session()
    with httpx.Client(cookies={"dis360_session": cookie}, follow_redirects=True) as client:
        chat = client.post(f"{BASE}/chat/new")
        chat_url = str(chat.url)
        conv_id = chat_url.rstrip("/").split("/")[-1]
        with (ROOT / "examples" / "sample_sales.csv").open("rb") as handle:
            client.post(
                f"{BASE}/chat/{conv_id}/upload",
                files={"data_file": ("sample_sales.csv", handle, "text/csv")},
            )
        client.post(
            f"{BASE}/chat/{conv_id}/message",
            data={"question": "Проанализируй продажи, найди основные тенденции и риски"},
        )
        with (ROOT / "examples" / "sample_sales.csv").open("rb") as handle:
            result = client.post(
                f"{BASE}/analyze",
                data={
                    "chart_type": "pie",
                    "x_column": "region",
                    "y_column": "revenue",
                    "analyst_mode": "business",
                    "question": "Проанализируй продажи, найди основные тенденции и риски",
                },
                files={"data_file": ("sample_sales.csv", handle, "text/csv")},
            )
        result_html = cfg.output_dir / "_promo_result.html"
        result_html.write_text(result.text, encoding="utf-8")

    profile = ROOT / ".chrome-shot"
    profile.mkdir(exist_ok=True)
    proc = subprocess.Popen(
        [
            str(BROWSER),
            f"--remote-debugging-port={PORT}",
            f"--user-data-dir={profile}",
            "--headless=new",
            "--disable-gpu",
            "--window-size=1920,1080",
            "--hide-scrollbars",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1.2)
        tab = wait_devtools()
        with connect(tab["webSocketDebuggerUrl"], max_size=30_000_000) as ws:
            cdp = CDP(ws)
            target = cdp.send("Target.createTarget", {"url": "about:blank"})
            attached = cdp.send(
                "Target.attachToTarget", {"targetId": target["targetId"], "flatten": True}
            )
            sid = attached["sessionId"]
            cdp.send("Page.enable", session_id=sid)
            cdp.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False},
                sid,
            )
            cdp.send("Network.enable", session_id=sid)
            cdp.send(
                "Network.setCookie",
                {"name": "dis360_session", "value": cookie, "url": BASE},
                sid,
            )

            def open_url(url: str, wait: float = 1.8) -> None:
                cdp.send("Page.navigate", {"url": url}, sid)
                time.sleep(wait)
                cdp.send("Runtime.evaluate", {"expression": PRIVACY_JS}, sid)
                time.sleep(0.25)

            open_url(f"{BASE}/")
            screenshot(cdp, sid, "01-landing.png")
            open_url(f"{BASE}/dashboard")
            screenshot(cdp, sid, "02-dashboard.png")
            open_url(chat_url)
            screenshot(cdp, sid, "03-chat.png")
            open_url(f"{BASE}/outputs/_promo_result.html", wait=2.2)
            screenshot(cdp, sid, "04-analysis.png")
            if pie_url:
                open_url(pie_url, wait=2.2)
                screenshot(cdp, sid, "05-pie.png")
            if scatter_url:
                open_url(scatter_url, wait=2.2)
                screenshot(cdp, sid, "06-scatter.png")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
