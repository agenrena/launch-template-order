"""The download supplies an initial name; this App owns it after initialization."""

import json

from django.conf import settings


def initial_software_name():
    try:
        config = json.loads(settings.SOFTWARE_CONFIG_FILE.read_text(encoding="utf-8"))
        name = config.get("software_name") if isinstance(config, dict) else None
        if isinstance(name, str) and 0 < len(name.strip()) <= 120:
            return name.strip()
    except (OSError, ValueError):
        pass
    return settings.SOFTWARE_DEFAULT_NAME
