#!/usr/bin/env python3
"""Check catalog/ and inventory/workstations/ against the lab's rules.

Run by tools/check (and so by CI on every push), and the same rules run inside `lab`
before every change (lablib.validate). Rules: names, VM ID ranges, addresses derived
from the VM ID, nothing used twice, every role in the catalogue, every catalogue entry
complete. Exit 1 with one line per problem.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "ansible" / "roles" / "runner" / "files"))
import lablib as L  # noqa: E402

REQUIRED = {"name": str, "description": str, "tools": list, "packages": list, "login_groups": list, "size": dict}


def main():
    cfg, cat = L.settings(REPO), L.catalog(REPO)
    problems = L.validate(L.fleet(REPO), cat, cfg)
    for role, entry in cat.items():
        for key, kind in REQUIRED.items():
            if not isinstance(entry.get(key), kind):
                problems.append(f"catalog/{role}.yml: '{key}' missing or not a {kind.__name__}")
        if set(entry.get("size") or {}) != {"cores", "memory_mb", "disk_gb"}:
            problems.append(f"catalog/{role}.yml: size needs cores, memory_mb, disk_gb")
    for p in problems:
        print(p)
    print(f"inventory: {len(L.fleet(REPO))} fleet machines, {len(cat)} catalogue entries, "
          f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
