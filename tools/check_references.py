#!/usr/bin/env python3
"""Keep the comments honest: every repository path a file mentions must exist.

Comments in this repo say where things live and how they connect ("deployed by
roles/portal", "see docs/self-service.md"). When a file moves, those comments are the
first thing to go stale. This finds every path-like mention in tracked text files and
fails if the path isn't there. Run by tools/check (and so by CI).

Recognised: paths starting with a top-level directory of the repo (ansible/, docs/,
terraform/, ...), and roles/<name> (meaning ansible/roles/<name>). Mentions containing
placeholders (<host>, *, {{ }}) are skipped.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOP = ["ansible", "catalog", "docs", "host-setup", "inventory", "terraform", "tests", "tools", "vps", ".github"]
TOP_RE = "|".join(map(re.escape, TOP))
PATH = re.compile(rf"(?<![\w/.:@-])((?:{TOP_RE})/[\w./-]*[\w-]|roles/[\w-]+(?:/[\w./-]*[\w-])?)")
SKIP_SUFFIX = (".lock.hcl", ".png", ".jpg", ".iso")


def main():
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    bad = []
    for name in files:
        path = REPO / name
        if name.endswith(SKIP_SUFFIX) or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for m in PATH.finditer(line):
                ref = m.group(1).rstrip(".")
                if any(c in line[max(0, m.start() - 2):m.end() + 2] for c in "<*{"):
                    continue
                target = REPO / ("ansible/" + ref if ref.startswith("roles/") else ref)
                if not target.exists():
                    bad.append(f"{name}:{n}: {ref} does not exist")
    for b in bad:
        print(b)
    print(f"references: {len(bad)} broken")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
