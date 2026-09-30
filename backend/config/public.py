"""The customer entrance: the only part of this App meant to be reached from outside.

On this computer the App listens on 127.0.0.1 only. When PUBLIC_PORT is set,
scripts/start.py also serves this entrance there, for a tunnel or reverse proxy
(Cloudflare Tunnel, Tailscale Funnel, ...) to publish; see docs/publish.md.

It passes on the ordering pages and their API and answers 404 for everything else
(console, first-owner setup, Agent API, MCP), however the tunnel is configured. A
tunnel connects from this computer, so the App cannot tell outside visitors apart
by address; keeping the console off this entrance is what keeps it private.
"""

# "/" is the menu (takeout, or ?table=A1 for dine-in), /d/ an Agent-prepared cart
# to confirm, /o/ an order's status page.
PUBLIC_PREFIXES = ("/api/web/", "/assets/", "/d/", "/o/")


def is_public(path):
    if ".." in path.split("/"):
        return False
    return path == "/" or path.startswith(PUBLIC_PREFIXES)


def public_only(app):
    def entrance(environ, start_response):
        if is_public(environ.get("PATH_INFO") or "/"):
            return app(environ, start_response)
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"Not found"]

    return entrance
