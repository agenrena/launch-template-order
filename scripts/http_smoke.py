"""Real HTTP check using an isolated, randomly named PostgreSQL database.

Requires DATABASE_URL for a development PostgreSQL role with CREATEDB, installed
backend dependencies and npm builds in frontend/mcp. Never runs against an
existing application database: creates and drops only its own smoke database.
"""

import http.cookiejar
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    source = os.environ["DATABASE_URL"]
    db_name = "order_smoke_" + secrets.token_hex(8)
    parts = urlsplit(source)
    dsn = urlunsplit(parts._replace(path="/" + db_name))
    control = psycopg2.connect(source)
    control.autocommit = True
    children = []
    created = False
    with tempfile.TemporaryFile(mode="w+") as logs:
        try:
            with control.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
            created = True
            api_port, mcp_port, web_port = port(), port(), port()
            base = f"http://127.0.0.1:{web_port}"
            password = secrets.token_urlsafe(32)
            env = {
                **os.environ,
                "DATABASE_URL": dsn,
                "SECRET_KEY": secrets.token_urlsafe(48),
                "COOKIE_SECURE": "false",
                "ALLOWED_HOSTS": "localhost,127.0.0.1",
                "CSRF_TRUSTED_ORIGINS": base,
                "BOOTSTRAP_ADMIN_USERNAME": "smoke_owner",
                "BOOTSTRAP_ADMIN_PASSWORD": password,
                "ORDER_API_URL": f"http://127.0.0.1:{api_port}/api/agent-api/",
                "ORDER_DEV_API": f"http://127.0.0.1:{api_port}",
                "ORDER_DEV_MCP": f"http://127.0.0.1:{mcp_port}",
                "PORT": str(mcp_port),
                # Agent confirmation links point at the Vite front end.
                "ORDER_PUBLIC_BASE_URL": base,
                # Never reach a real Agenrena from a smoke run.
                "AGENRENA_VENDOR_ID": "",
                "AGENRENA_VENDOR_SECRET": "",
            }

            def manage(*args):
                subprocess.run(
                    [sys.executable, "backend/manage.py", *args],
                    cwd=ROOT,
                    env=env,
                    stdout=logs,
                    stderr=logs,
                    check=True,
                )

            manage("migrate", "--noinput")
            manage("runtime_bootstrap")
            manage("makemigrations", "--check", "--dry-run")
            for args in [
                [
                    sys.executable,
                    "backend/manage.py",
                    "runserver",
                    f"127.0.0.1:{api_port}",
                    "--noreload",
                ],
                ["node", "mcp/dist/index.js"],
                [
                    "node",
                    "frontend/node_modules/vite/bin/vite.js",
                    "frontend",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(web_port),
                    "--strictPort",
                ],
            ]:
                children.append(subprocess.Popen(args, cwd=ROOT, env=env, stdout=logs, stderr=logs))
            for url in [
                f"http://127.0.0.1:{api_port}/health/",
                f"http://127.0.0.1:{mcp_port}/health/",
                base,
            ]:
                for attempt in range(100):
                    try:
                        with urllib.request.urlopen(url, timeout=2) as response:
                            assert response.status == 200
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if any(p.poll() is not None for p in children):
                            raise RuntimeError("A smoke process exited early.")
                        if attempt == 99:
                            raise
                        time.sleep(0.1)
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
            )
            csrf = ""

            def request(path, data=None, method=None):
                nonlocal csrf
                req = urllib.request.Request(
                    base + "/api/console/" + path,
                    data=None if data is None else json.dumps(data).encode(),
                    method=method,
                    headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
                )
                with opener.open(req, timeout=5) as response:
                    result = json.load(response)
                csrf = result.get("csrf_token", csrf) if isinstance(result, dict) else csrf
                return result

            request("session/")
            assert (
                request("login/", {"username": "smoke_owner", "password": password})["user"]["role"]
                == "owner"
            )
            assert (
                request("business/", {"name": "Smoke business"}, "PATCH")["name"]
                == "Smoke business"
            )
            # Without injected Vendor credentials the App runs without Agenrena.
            assert request("agenrena/") == {"configured": False, "status": "none"}
            key = request("keys/", {"label": "Smoke MCP", "role": "customer_service"})

            # The menu, hours and a table, as staff would set them up.
            mains = request("categories/", {"name": "主餐"})
            size = request(
                "option-groups/",
                {
                    "name": "份量",
                    "min_select": 1,
                    "max_select": 1,
                    "options": [{"name": "一般"}, {"name": "加大", "price_delta": "20"}],
                },
            )
            regular, large = (o["id"] for o in size["options"])
            burger = request(
                "menu-items/",
                {
                    "category": mains["id"],
                    "name": "牛肉堡",
                    "price": "120",
                    "option_groups": [size["id"]],
                },
            )
            request("tables/", {"code": "A1"})
            all_day = [{"opens_at": "00:00", "closes_at": "23:59"}]
            request(
                "hours/",
                {"weekly": [{"weekday": d, "intervals": all_day} for d in range(7)]},
                "PUT",
            )

            def public(path, data=None):
                req = urllib.request.Request(
                    base + "/api/web/" + path,
                    data=None if data is None else json.dumps(data).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    return json.load(response)

            store = public("store/")
            assert store["accepting_orders"] and store["menu"][0]["items"][0]["name"] == "牛肉堡"
            takeout = public(
                "orders/", {"phone": "0912", "items": [{"item": burger["id"], "options": [large]}]}
            )
            assert takeout["pickup_code"] == "1" and takeout["rounds"][0]["status"] == "pending"
            assert takeout["rounds"][0]["items"][0]["total"] == "140.00"
            # Pausing stops the public page; resuming reopens it.
            request("ordering-status/", {"action": "pause", "minutes": 15, "reason": "忙"})
            assert public("store/")["paused"] is True
            request("ordering-status/", {"action": "resume"})
            assert public("store/")["accepting_orders"] is True
            table = public("tabs/", {"table": "A1"})
            assert public("tabs/", {"table": "A1"})["access_token"] == table["access_token"]
            dine = public(
                f"tabs/{table['access_token']}/rounds/",
                {"items": [{"item": burger["id"], "options": [regular]}]},
            )
            assert len(dine["rounds"]) == 1

            subprocess.run(
                ["node", "mcp/tests/http-smoke.mjs"],
                cwd=ROOT,
                env={
                    **env,
                    "SMOKE_MCP_URL": base + "/mcp",
                    "SMOKE_AGENT_KEY": key["secret"],
                    "SMOKE_ORDER": json.dumps(
                        {"item": burger["id"], "option": large, "base": base}
                    ),
                },
                check=True,
            )

            # Staff: the service screen sees all three entrances and acts on them.
            service = request("tabs/")
            assert sorted(t["rounds"][0]["source"] for t in service) == [
                "agent",
                "customer",
                "customer",
            ]
            qr = next(t for t in service if t["pickup_code"] == "1")
            done = request(f"rounds/{qr['rounds'][0]['id']}/confirm/", {})
            assert done["rounds"][0]["status"] == "confirmed" and done["total"] == "140.00"
            assert request("sales/today/")["revenue"] == "140.00"
            request(f"rounds/{qr['rounds'][0]['id']}/complete/", {})
            table_tab = next(t for t in service if t["table_code"] == "A1")
            closed = request(f"tabs/{table_tab['id']}/close/", {})
            assert closed["closed_at"]
            print(
                "Ordering HTTP: QR takeout/dine-in, Agent link, customer confirm, staff service passed."
            )
            assert request("audit/")["count"] >= 5
            request(f"keys/{key['id']}/revoke/", {})
            req = urllib.request.Request(
                base + "/mcp",
                data=b"{}",
                headers={
                    "Authorization": "Bearer " + key["secret"],
                    "Content-Type": "application/json",
                },
            )
            try:
                urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
            else:
                raise AssertionError("Revoked key was accepted")
            request("logout/", {})
            assert request("session/")["user"] is None
            print(
                "Real HTTP: frontend/proxy, session, CSRF login, settings, audit and revoked-key rejection passed."
            )
        except Exception:
            # Logs contain only synthetic test data, never print environment/credentials.
            logs.seek(0)
            output = logs.read()
            if "password" in locals():
                output = output.replace(password, "[redacted]")
            if "key" in locals():
                output = output.replace(key["secret"], "[redacted]")
            sys.stderr.write(output[-6000:])
            raise
        finally:
            for child in reversed(children):
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            if created:
                with control.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db_name))
                    )
            control.close()


if __name__ == "__main__":
    main()
