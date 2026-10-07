"""Environment capture. Results are scoped to the recorded backend."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import ssl
import subprocess
import sys
from datetime import datetime, timezone


def _git_revision() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _cpu_model() -> str | None:
    try:
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or None


def _cpu_frequency() -> dict | None:
    try:
        import psutil

        freq = psutil.cpu_freq()
        return {"current_mhz": freq.current, "min_mhz": freq.min, "max_mhz": freq.max}
    except Exception:
        return None


def _package_versions() -> dict:
    versions = {}
    for name in ("numpy", "pandas", "scipy", "matplotlib", "yaml", "psutil", "pytest"):
        try:
            module = __import__(name)
            versions[name] = getattr(module, "__version__", "unknown")
        except Exception:
            versions[name] = None
    return versions


def capture(extra: dict | None = None) -> dict:
    try:
        import psutil

        total_ram = psutil.virtual_memory().total
    except Exception:
        total_ram = None

    info = {
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "git_revision": _git_revision(),
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": _cpu_model(),
        "cpu_count_logical": os.cpu_count(),
        "cpu_frequency": _cpu_frequency(),
        "total_ram_bytes": total_ram,
        # The hash backend is recorded because all conclusions about SHA-256,
        # SHA3-256 and BLAKE2s apply to these hashlib implementations on this
        # build, not to the algorithms in general.
        "openssl_version": ssl.OPENSSL_VERSION,
        "hashlib_algorithms_available": sorted(hashlib.algorithms_available),
        "packages": _package_versions(),
    }
    if extra:
        info.update(extra)
    return info


def write(path: str, extra: dict | None = None) -> dict:
    info = capture(extra)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(info, fh, indent=2, sort_keys=True)
    return info
