"""Run this store's App on this computer: one folder, no Docker, no database server.

Started by start.command (macOS/Linux) or start.bat (Windows), which run:

    uv run --no-project --python 3.13 --with-requirements backend/requirements.txt \
        python scripts/start.py [--no-browser]

Creates .env on first run, builds the frontend and MCP when their sources changed,
migrates data/db.sqlite3 and serves http://127.0.0.1:<PORT from .env> until Ctrl+C.

`start.command manage <command> ...` runs a Django management command with this
install's settings, e.g. `./start.command manage changepassword owner`.
"""

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from setup import ROOT, create_env


def load_env():
    """Read .env into the environment; values already set by the caller win."""
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def newest(folder):
    times = [
        p.stat().st_mtime
        for p in folder.rglob("*")
        if p.is_file() and not {"node_modules", "dist"} & set(p.relative_to(folder).parts)
    ]
    return max(times, default=0)


def build(npm, name, output):
    """Install and build a Node part only when it is missing or its sources changed."""
    folder = ROOT / name
    installed = folder / "node_modules" / ".package-lock.json"
    if (
        not installed.exists()
        or installed.stat().st_mtime < (folder / "package-lock.json").stat().st_mtime
    ):
        print(f"安裝 {name} 套件…", flush=True)
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=folder, check=True)
    target = folder / output
    if not target.exists() or target.stat().st_mtime < newest(folder):
        print(f"建置 {name}…", flush=True)
        subprocess.run([npm, "run", "build"], cwd=folder, check=True)


def check_node():
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        raise SystemExit("需要 Node.js 22.12 以上版本（可以請你的 Agent 安裝）：https://nodejs.org")
    version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout
    major, minor = (int(n) for n in version.strip().lstrip("v").split(".")[:2])
    if (major, minor) < (22, 12):
        raise SystemExit(f"Node.js 版本是 {version.strip()}，需要 22.12 以上。")
    return npm


def healthy(url):
    try:
        with urllib.request.urlopen(url + "/health/", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def main():
    if create_env():
        print("已建立 .env（這台電腦專用的密鑰）。")
    load_env()
    os.environ["LOCAL_APP"] = "true"
    if sys.argv[1:2] == ["manage"]:
        command = [sys.executable, "backend/manage.py", *sys.argv[2:]]
        raise SystemExit(subprocess.run(command, cwd=ROOT).returncode)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    args = parser.parse_args()
    host = os.environ.get("BIND_ADDRESS") or "127.0.0.1"
    port = int(os.environ.get("PORT") or 8084)
    url = f"http://127.0.0.1:{port}"
    console = url + "/console/"  # "/" is the customer ordering page
    if healthy(url):
        print(f"這間店的 App 已經在執行：{console}")
        if not args.no_browser:
            webbrowser.open(console)
        return

    npm = check_node()
    build(npm, "frontend", "dist/index.html")
    build(npm, "mcp", "dist/index.js")
    subprocess.run(
        [sys.executable, "backend/manage.py", "migrate", "--noinput"], cwd=ROOT, check=True
    )

    def announce():
        while not healthy(url):
            time.sleep(0.2)
        print(f"\n這間店的 App 已經開好：{console}")
        print("資料在 data/ 資料夾。按 Ctrl+C 或關掉這個視窗就會停止。\n", flush=True)
        if not args.no_browser:
            webbrowser.open(console)

    threading.Thread(target=announce, daemon=True).start()
    sys.path.insert(0, str(ROOT / "backend"))
    from config.public import public_only
    from config.wsgi import application
    from waitress import create_server, serve

    # The customer entrance (docs/publish.md): only the ordering pages, for a
    # tunnel to publish. Unset means customers' phones cannot reach this App.
    public_port = os.environ.get("PUBLIC_PORT")
    if public_port:
        entrance = create_server(
            public_only(application),
            host="127.0.0.1",
            port=int(public_port),
            threads=8,
            # Only the tunnel on this computer can connect here, so trust the
            # customer's address it forwards; otherwise every customer shares
            # one address and one ordering rate limit.
            trusted_proxy="127.0.0.1",
            trusted_proxy_count=1,
            trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"},
        )
        threading.Thread(target=entrance.run, daemon=True).start()
        public_url = os.environ.get("ORDER_PUBLIC_BASE_URL") or "（還沒填 ORDER_PUBLIC_BASE_URL）"
        print(f"顧客點餐入口：http://127.0.0.1:{public_port} → {public_url}", flush=True)
    serve(application, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()
