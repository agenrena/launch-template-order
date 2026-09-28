"""Generate local deployment secrets. Never overwrite an existing .env."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
path = root / ".env"
try:
    with path.open("x") as output:
        path.chmod(0o600)
        template = (root / ".env.example").read_text()
        output.write(
            template.replace("GENERATE_SECRET_KEY", secrets.token_urlsafe(48)).replace(
                "GENERATE_DATABASE_PASSWORD", secrets.token_hex(24)
            )
        )
except FileExistsError:
    raise SystemExit(".env already exists; left unchanged.")
print("Created .env. Next: docker compose up --build -d")
