"""Generate this install's private secrets. Never overwrite an existing .env."""

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def create_env():
    """Write .env with fresh secrets. Returns False when it already exists."""
    path = ROOT / ".env"
    try:
        with path.open("x") as output:
            path.chmod(0o600)
            template = (ROOT / ".env.example").read_text()
            output.write(
                template.replace("GENERATE_SECRET_KEY", secrets.token_urlsafe(48)).replace(
                    "GENERATE_DATABASE_PASSWORD", secrets.token_hex(24)
                )
            )
    except FileExistsError:
        return False
    return True


if __name__ == "__main__":
    if not create_env():
        raise SystemExit(".env already exists; left unchanged.")
    print("Created .env. Next: ./start.command (this computer) or docker compose up --build -d")
