#!/usr/bin/env python3
"""Check catalog/, inventory/workstations/ and inventory/teams.yml against the lab's rules.

Run by tools/check (and so by CI on every push), and the same rules run inside `lab`
before every change (lablib.validate). Rules: names, VM ID ranges, addresses derived
from the VM ID, nothing used twice, every role in the catalogue, every catalogue entry
complete, every team well-formed (unique gid, a real default role) and every login group
a team's security group. Exit 1 with one line per problem.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "ansible" / "roles" / "runner" / "files"))
import lablib as L  # noqa: E402

REQUIRED = {"kind": str, "name": str, "description": str, "tools": list, "packages": list, "login_groups": list, "size": dict}


def main():
    cfg, cat = L.settings(REPO), L.catalog(REPO)
    problems = L.validate(L.fleet(REPO), cat, cfg)
    for role, entry in cat.items():
        for key, kind in REQUIRED.items():
            if not isinstance(entry.get(key), kind):
                problems.append(f"catalog/{role}.yml: '{key}' missing or not a {kind.__name__}")
        if entry.get("kind") not in cfg["staff_limits"]:
            problems.append(f"catalog/{role}.yml: kind must be one of {', '.join(cfg['staff_limits'])}")
        if set(entry.get("size") or {}) != {"cores", "memory_mb", "disk_gb"}:
            problems.append(f"catalog/{role}.yml: size needs cores, memory_mb, disk_gb")
    teams = L.teams(REPO)
    groups = {f"security-{t}" for t in teams} | set(cfg["ad_admin_groups"])
    for role, entry in cat.items():
        for g in set(entry.get("login_groups") or []) - groups:
            problems.append(f"catalog/{role}.yml: login group {g} is no team's (inventory/teams.yml)")
    gids = {}
    for key, t in teams.items():
        if not L.USER_RE.fullmatch(key) or not isinstance(t.get("name"), str):
            problems.append(f"inventory/teams.yml: {key}: needs a lowercase key and a name")
        if t.get("role") not in cat:
            problems.append(f"inventory/teams.yml: {key}: role {t.get('role')!r} is not in catalog/")
        if not isinstance(t.get("gid"), int) or t["gid"] in gids:
            problems.append(f"inventory/teams.yml: {key}: gid must be a number no other team has")
        gids[t.get("gid")] = key
    for p in problems:
        print(p)
    print(f"inventory: {len(L.fleet(REPO))} fleet machines, {len(cat)} catalogue entries, "
          f"{len(teams)} teams, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
