"""Tiny .env loader (no dependency). Values are never printed or logged."""
import os
from pathlib import Path


def parse_env(text):
    """Parse KEY=VALUE lines. Ignores blank lines and # comments; allows `export ` and quotes."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:  # inline comment on an unquoted value
            val = val.split(" #", 1)[0].rstrip()
        if key:
            out[key] = val
    return out


def load_dotenv(path, environ=None):
    """Set variables from `path` into `environ` (default os.environ) when unset or empty.

    Returns the names that were set (never the values). Missing file -> no-op.
    """
    environ = os.environ if environ is None else environ
    path = Path(path)
    if not path.is_file():
        return []
    loaded = []
    for key, val in parse_env(path.read_text()).items():
        if val and not environ.get(key):
            environ[key] = val
            loaded.append(key)
    return loaded
