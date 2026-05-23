import os
from pathlib import Path
from typing import Optional


def load_local_env(env_path: Optional[str | Path] = None) -> None:
    if os.environ.get("PRISM_SKIP_DOTENV", "").strip().lower() == "true":
        return

    path = Path(env_path) if env_path else Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]

        os.environ[key] = value
