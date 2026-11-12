from __future__ import annotations

import json
from datetime import UTC, datetime

from .config import ProjectConfig
from .records import TAKEOFF


def takeoff(config: ProjectConfig) -> dict:
    payload = {"generated_utc": datetime.now(UTC).isoformat(), "records": TAKEOFF}
    directory = config.root / "data" / "takeoff"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "takeoff.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
