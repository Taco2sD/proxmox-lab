#!/usr/bin/env python3
"""The knowledge base's checker and generator (docs/kb/README.md explains the KB).

    python3 tools/kb.py check    validate every page and fail if anything generated is stale
    python3 tools/kb.py build    regenerate docs/kb/INDEX.md, docs/kb/kb.json and the
                                 generated blocks inside pattern and runbook pages

What `check` enforces (tools/check runs it, so CI does too):
  - each page type's front matter: required keys, allowed values, id = file name
  - every reference resolves: components and hosts (docs/kb/components.yml), patterns,
    related issues, plans' issues
  - components.yml itself: unique ids, known kinds, real role and doc paths, depends_on
    pointing at real components, no dependency cycles
  - every alert rule in ansible/roles/monitoring/files/alerts.yml has a runbook page and
    a runbook_url annotation pointing at it, and no runbook is left without its alert
  - generated content is what `build` would write now (so the index can't drift from the
    pages it summarises)

Generated content is deterministic (sorted, no timestamps): running build twice changes
nothing, and a diff of INDEX.md shows exactly what the knowledge changed.
"""
import datetime
import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
RUNBOOK_BASE = "https://github.com/Taco2sD/proxmox-lab/blob/main/docs/kb/runbooks/"
START, END = "<!-- kb:generated:start -->", "<!-- kb:generated:end -->"

FOUND_BY = ("monitoring", "build", "investigation", "user", "ci", "review")
STATUS = ("fixed", "mitigated", "open", "accepted")
SEVERITY = ("low", "medium", "high", "critical")
ALERT_SEVERITY = ("critical", "warning", "info")
PLAN_STATUS = ("proposed", "in-progress", "done")
KINDS = ("host", "service", "pipeline", "external")
ISSUE_SECTIONS = ("Symptom", "How it was found", "Root cause", "Fix", "Verification", "Prevention")
PATTERN_SECTIONS = ("What happens", "How to spot it", "How to fix", "How to prevent")
RUNBOOK_SECTIONS = ("What it means", "First five minutes", "Common causes", "Escalate / fix")
PLAN_SECTIONS = ("Goal", "Why", "Steps", "Risks and rollback", "Done when")
ISSUE_FILE = re.compile(r"^(KB-\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*$")
PLAN_FILE = re.compile(r"^(PLAN-\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
FOUND_BY_MEANING = {
    "monitoring": "an alert or dashboard of the monitoring stack surfaced it",
    "build": "hit while building or changing something",
    "investigation": "noticed incidentally while investigating something else",
    "user": "a person reported it",
    "ci": "the checks (tools/check) caught it",
    "review": "anticipated by a deliberate review before it caused harm",
}


# ---------------------------------------------------------------- reading pages
class Page:
    """One Markdown page: its front matter, its body, where it lives."""

    def __init__(self, path, meta, body):
        self.path, self.meta, self.body = path, meta, body

    @property
    def stem(self):
        return self.path.stem


def parse(path):
    """Front matter (YAML between the first two '---' lines) and the body. Raises
    ValueError with a readable reason if the page has none or it isn't a mapping."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("no front matter (the page must start with a '---' line)")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("front matter is not closed by a '---' line")
    meta = yaml.safe_load(text[4:end]) or {}
    if not isinstance(meta, dict):
        raise ValueError("front matter is not a YAML mapping")
    return Page(path, meta, text[end + 5:])


def sections(body):
    """The page's '## ' headings, in order."""
    return [m.group(1).strip() for m in re.finditer(r"^## (.+)$", body, re.M)]


def as_date(value):
    """YAML gives unquoted dates as datetime.date; quoted ones as text. Both are fine."""
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


def jsonable(value):
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value


# ---------------------------------------------------------------- the knowledge base
class KB:
    def __init__(self, repo=REPO):
        self.repo = Path(repo)
        self.root = self.repo / "docs" / "kb"
        self.problems = []
        self.components = {}
        self.issues, self.patterns, self.runbooks, self.plans = {}, {}, {}, {}
        self.alerts = {}             # alert name -> its annotations
        self._load()

    def problem(self, where, text):
        rel = where.relative_to(self.repo) if isinstance(where, Path) else where
        self.problems.append(f"{rel}: {text}")

    # -------------------------------------------------------------- loading
    def _load(self):
        self._load_components()
        for folder, store in (("issues", self.issues), ("patterns", self.patterns),
                              ("runbooks", self.runbooks), ("plans", self.plans)):
            for path in sorted((self.root / folder).glob("*.md")):
                if path.name == "README.md":        # a folder's own introduction, not a page
                    continue
                try:
                    store[path.stem] = parse(path)
                except (ValueError, yaml.YAMLError) as e:
                    self.problem(path, str(e).splitlines()[0])
        self._load_alerts()

    def _load_components(self):
        path = self.root / "components.yml"
        if not path.exists():
            self.problem(path, "missing")
            return
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for c in data.get("components") or []:
            cid = c.get("id") if isinstance(c, dict) else None
            if not cid:
                self.problem(path, f"component without an id: {c!r}")
            elif cid in self.components:
                self.problem(path, f"component {cid} is listed twice")
            else:
                self.components[cid] = c

    def _load_alerts(self):
        path = self.repo / "ansible" / "roles" / "monitoring" / "files" / "alerts.yml"
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for group in data.get("groups") or []:
            for rule in group.get("rules") or []:
                if "alert" in rule:
                    self.alerts[rule["alert"]] = rule.get("annotations") or {}

    # -------------------------------------------------------------- helpers
    @property
    def hosts(self):
        return {cid for cid, c in self.components.items() if c.get("kind") == "host"}

    def issues_sorted(self):
        return [self.issues[k] for k in sorted(self.issues)]

    def link(self, page, frm):
        """A relative link from the folder of `frm` (a path under docs/kb) to a page."""
        rel = Path(*[".."] * len(frm.parent.relative_to(self.root).parts)) / page.path.relative_to(self.root)
        return rel.as_posix()

    # -------------------------------------------------------------- validation
    def validate(self):
        self._check_components()
        for kind, store, key in (("issue", self.issues, "id"), ("plan", self.plans, "plan")):
            seen = Counter(p.meta.get(key) for p in store.values())
            for value, n in sorted((v, n) for v, n in seen.items() if n > 1 and v):
                self.problems.append(f"docs/kb: {kind} id {value} is used by {n} files")
        for p in self.issues.values():
            self._check_issue(p)
        for p in self.patterns.values():
            self._check_pattern(p)
        for p in self.runbooks.values():
            self._check_runbook(p)
        for p in self.plans.values():
            self._check_plan(p)
        self._check_alerts()
        return self.problems

    def _require(self, page, keys):
        missing = [k for k in keys if k not in page.meta]
        if missing:
            self.problem(page.path, f"front matter is missing {', '.join(missing)}")
        return not missing

    def _check_list(self, page, key, valid, what):
        value = page.meta.get(key)
        if not isinstance(value, list):
            self.problem(page.path, f"{key} must be a list (use [] for none)")
            return
        for v in value:
            if v not in valid:
                self.problem(page.path, f"{key}: unknown {what} {v!r}")

    def _check_sections(self, page, wanted):
        have = [s for s in sections(page.body) if s in wanted]
        if have != list(wanted):
            self.problem(page.path, f"body needs the sections {', '.join('## ' + s for s in wanted)} in that order "
                                    f"(found: {', '.join(have) or 'none'})")

    def _check_block(self, page):
        if page.body.count(START) != 1 or page.body.count(END) != 1:
            self.problem(page.path, f"needs exactly one {START} ... {END} block (tools/kb.py build fills it)")

    def _check_components(self):
        path = self.root / "components.yml"
        for cid, c in sorted(self.components.items()):
            where = f"{path.relative_to(self.repo)} [{cid}]"
            if not SLUG.match(cid):
                self.problems.append(f"{where}: id must be kebab-case")
            for key in ("name", "kind", "description"):
                if not c.get(key):
                    self.problems.append(f"{where}: missing {key}")
            if c.get("kind") not in KINDS:
                self.problems.append(f"{where}: kind must be one of {', '.join(KINDS)}")
            host = c.get("host")
            if c.get("kind") != "host" and host not in self.hosts:
                self.problems.append(f"{where}: host {host!r} is not a host component")
            if c.get("kind") == "host" and host is not None and host not in self.hosts:
                self.problems.append(f"{where}: host {host!r} (where this host runs) is not a host component")
            for dep in c.get("depends_on") or []:
                if dep not in self.components:
                    self.problems.append(f"{where}: depends_on {dep!r} is not a component")
            for rel in (c.get("roles") or []) + (c.get("docs") or []):
                if not (self.repo / rel).exists():
                    self.problems.append(f"{where}: {rel} does not exist")
        # No cycles: a dependency map with a loop can't say what breaks what
        state = {}

        def visit(cid, trail):
            if state.get(cid) == "done":
                return
            if state.get(cid) == "active":
                loop = trail[trail.index(cid):] + [cid]
                self.problems.append(f"{path.relative_to(self.repo)}: dependency cycle {' -> '.join(loop)}")
                return
            state[cid] = "active"
            for dep in self.components[cid].get("depends_on") or []:
                if dep in self.components:
                    visit(dep, trail + [cid])
            state[cid] = "done"

        for cid in sorted(self.components):
            visit(cid, [])

    def _check_issue(self, p):
        m = ISSUE_FILE.match(p.stem)
        if not m:
            self.problem(p.path, "file name must be KB-NNNN-<slug>.md (slug: lowercase letters, digits, '-')")
        keys = ("id", "title", "status", "found_by", "signal", "found", "severity", "hosts", "components",
                "patterns", "commits", "related")
        if not self._require(p, keys):
            return
        meta = p.meta
        if m and meta["id"] != m.group(1):
            self.problem(p.path, f"id {meta['id']!r} doesn't match the file name ({m.group(1)})")
        for key, allowed in (("status", STATUS), ("found_by", FOUND_BY), ("severity", SEVERITY)):
            if meta[key] not in allowed:
                self.problem(p.path, f"{key} must be one of {', '.join(allowed)} (is {meta[key]!r})")
        if not str(meta.get("title") or "").strip() or not str(meta.get("signal") or "").strip():
            self.problem(p.path, "title and signal can't be empty")
        if as_date(meta["found"]) is None:
            self.problem(p.path, "found must be a date (YYYY-MM-DD)")
        if meta["status"] in ("fixed", "mitigated"):
            if as_date(meta.get("resolved")) is None:
                self.problem(p.path, f"status {meta['status']} needs resolved: YYYY-MM-DD")
            elif as_date(meta["found"]) and as_date(meta["resolved"]) < as_date(meta["found"]):
                self.problem(p.path, "resolved is before found")
        elif "resolved" in meta:
            self.problem(p.path, f"status {meta['status']} must not have resolved (it isn't)")
        self._check_list(p, "hosts", self.hosts, "host")
        self._check_list(p, "components", self.components, "component")
        self._check_list(p, "patterns", self.patterns, "pattern")
        self._check_list(p, "related", {pg.meta.get("id") for pg in self.issues.values()}, "issue")
        related = meta.get("related") if isinstance(meta.get("related"), list) else []
        if meta["id"] in related:
            self.problem(p.path, "related lists the issue itself")
        commits = meta.get("commits")
        if not isinstance(commits, list) or any(not COMMIT.match(str(c)) for c in commits):
            self.problem(p.path, "commits must be a list of commit hashes (7-40 hex characters)")
        self._check_sections(p, ISSUE_SECTIONS)

    def _check_pattern(self, p):
        if not SLUG.match(p.stem):
            self.problem(p.path, "file name must be a kebab-case slug")
        if not self._require(p, ("pattern", "title", "components")):
            return
        if p.meta["pattern"] != p.stem:
            self.problem(p.path, f"pattern {p.meta['pattern']!r} doesn't match the file name")
        self._check_list(p, "components", self.components, "component")
        self._check_sections(p, PATTERN_SECTIONS)
        self._check_block(p)

    def _check_runbook(self, p):
        if not self._require(p, ("alert", "severity", "components")):
            return
        if p.meta["alert"] != p.stem:
            self.problem(p.path, f"alert {p.meta['alert']!r} doesn't match the file name")
        if p.meta["severity"] not in ALERT_SEVERITY:
            self.problem(p.path, f"severity must be one of {', '.join(ALERT_SEVERITY)}")
        self._check_list(p, "components", self.components, "component")
        self._check_sections(p, RUNBOOK_SECTIONS)
        self._check_block(p)

    def _check_plan(self, p):
        m = PLAN_FILE.match(p.stem)
        if not m:
            self.problem(p.path, "file name must be PLAN-NNNN-<slug>.md")
        if not self._require(p, ("plan", "title", "status", "created", "issues", "patterns", "components")):
            return
        if m and p.meta["plan"] != m.group(1):
            self.problem(p.path, f"plan {p.meta['plan']!r} doesn't match the file name ({m.group(1)})")
        if p.meta["status"] not in PLAN_STATUS:
            self.problem(p.path, f"status must be one of {', '.join(PLAN_STATUS)}")
        if as_date(p.meta["created"]) is None:
            self.problem(p.path, "created must be a date (YYYY-MM-DD)")
        self._check_list(p, "issues", {pg.meta.get("id") for pg in self.issues.values()}, "issue")
        self._check_list(p, "patterns", self.patterns, "pattern")
        self._check_list(p, "components", self.components, "component")
        self._check_sections(p, PLAN_SECTIONS)

    def _check_alerts(self):
        alerts_file = "ansible/roles/monitoring/files/alerts.yml"
        for name, annotations in sorted(self.alerts.items()):
            if name not in self.runbooks:
                self.problems.append(f"{alerts_file}: alert {name} has no runbook (docs/kb/runbooks/{name}.md)")
            want = f"{RUNBOOK_BASE}{name}.md"
            if annotations.get("runbook_url") != want:
                self.problems.append(f"{alerts_file}: alert {name} needs annotation runbook_url: {want}")
        for name, page in sorted(self.runbooks.items()):
            if self.alerts and name not in self.alerts:
                self.problem(page.path, f"no alert rule named {name} in {alerts_file} (rename or delete the runbook)")

    # -------------------------------------------------------------- rendering
    def issue_row(self, issue, frm, cols=("id", "title", "status", "found_by", "hosts")):
        cells = []
        for col in cols:
            v = issue.meta.get(col, "")
            if col == "id":
                v = f"[{v}]({self.link(issue, frm)})"
            elif isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            elif isinstance(v, datetime.date):
                v = v.isoformat()
            cells.append(str(v).replace("|", "\\|"))
        return "| " + " | ".join(cells) + " |"

    def issue_table(self, issues, frm, cols=("id", "title", "status", "found_by", "hosts")):
        if not issues:
            return ["_None recorded yet._"]
        heads = {"id": "Issue", "title": "Problem", "status": "Status", "found_by": "Found by", "hosts": "Hosts",
                 "severity": "Severity", "found": "Found", "signal": "Signal", "components": "Components"}
        return ["| " + " | ".join(heads[c] for c in cols) + " |", "|" + "---|" * len(cols)] + \
               [self.issue_row(i, frm, cols) for i in issues]

    def pattern_block(self, page):
        mine = [i for i in self.issues_sorted() if page.stem in (i.meta.get("patterns") or [])]
        lines = ["### Issues with this pattern", "", "Generated by `tools/kb.py build` from the issues' `patterns`.", ""]
        return lines + self.issue_table(mine, page.path, ("id", "title", "status", "found_by", "hosts"))

    def runbook_block(self, page):
        mine = [i for i in self.issues_sorted() if str(i.meta.get("signal")) == page.stem]
        lines = ["### Past occurrences", "", "Generated by `tools/kb.py build`: issues whose `signal` is this alert.", ""]
        lines += self.issue_table(mine, page.path, ("id", "title", "status", "found", "hosts"))
        pats = sorted({pt for i in mine for pt in (i.meta.get("patterns") or []) if pt in self.patterns})
        if pats:
            lines += ["", "Patterns behind them: " + ", ".join(
                f"[{pt}]({self.link(self.patterns[pt], page.path)})" for pt in pats) + "."]
        return lines

    @staticmethod
    def with_block(body_text, block_lines):
        """The page's text with its generated block replaced (markers kept)."""
        if START not in body_text or END not in body_text:
            return body_text
        head, rest = body_text.split(START, 1)
        _, tail = rest.split(END, 1)
        return head + START + "\n" + "\n".join(block_lines) + "\n" + END + tail

    def render(self):
        """{path: text} for everything build writes."""
        out = {}
        for store, block in ((self.patterns, self.pattern_block), (self.runbooks, self.runbook_block)):
            for page in store.values():
                text = page.path.read_text(encoding="utf-8")
                out[page.path] = self.with_block(text, block(page))
        out[self.root / "INDEX.md"] = self.render_index()
        out[self.root / "kb.json"] = self.render_json()
        return out

    def render_json(self):
        def pages(store):
            return [{"path": p.path.relative_to(self.repo).as_posix(), **jsonable(p.meta)}
                    for _, p in sorted(store.items())]
        data = {
            "about": "Generated by tools/kb.py build from docs/kb (docs/kb/README.md). Do not edit.",
            "found_by": FOUND_BY_MEANING,
            "components": [jsonable(self.components[k]) for k in sorted(self.components)],
            "issues": pages(self.issues),
            "patterns": pages(self.patterns),
            "runbooks": pages(self.runbooks),
            "plans": pages(self.plans),
            "alerts": sorted(self.alerts),
        }
        return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"

    def render_index(self):
        index = self.root / "INDEX.md"
        issues = self.issues_sorted()
        L = ["# Knowledge base index", "",
             "Generated by `python3 tools/kb.py build` from the pages in this folder: don't edit by hand.",
             "How the knowledge base works: [README.md](README.md). Everything below, as data: [kb.json](kb.json).", ""]
        n_open = sum(1 for i in issues if i.meta.get("status") in ("open", "accepted"))
        L += [f"**{len(issues)} issues** ({n_open} open or accepted), **{len(self.patterns)} patterns**, "
              f"**{len(self.runbooks)} runbooks**, **{len(self.plans)} plans**, "
              f"**{len(self.components)} components**.", ""]

        def tally(title, key, order=None, meaning=None):
            counts = Counter()
            for i in issues:
                v = i.meta.get(key)
                for x in (v if isinstance(v, list) else [v]):
                    counts[str(x)] += 1
            keys = [k for k in (order or []) if counts[k]] + sorted(k for k in counts if k not in (order or []))
            out = [f"### {title}", "", "| | Issues |" if not meaning else "| | Issues | Meaning |",
                   "|---|---|" if not meaning else "|---|---|---|"]
            for k in keys:
                out.append(f"| {k} | {counts[k]} |" + (f" {meaning.get(k, '')} |" if meaning else ""))
            return out + [""] if keys else out + ["| none | 0 |" + (" |" if meaning else ""), ""]

        L += ["## Tallies", ""]
        L += tally("How problems were found", "found_by", FOUND_BY, FOUND_BY_MEANING)
        L += tally("Status", "status", STATUS)
        L += tally("Severity", "severity", list(reversed(SEVERITY)))
        L += tally("Hosts", "hosts")

        L += ["## Open and accepted", "",
              "Known problems that aren't fixed: accepted ones were judged not worth fixing (the page says why).", ""]
        L += self.issue_table([i for i in issues if i.meta.get("status") in ("open", "accepted")], index,
                              ("id", "title", "status", "severity", "found_by", "hosts"))

        L += ["", "## Found by the monitoring", "",
              "Problems an alert or dashboard surfaced (`found_by: monitoring`), as opposed to ones hit while building, "
              "stumbled on, reported or anticipated: what the monitoring has earned so far.", ""]
        L += self.issue_table([i for i in issues if i.meta.get("found_by") == "monitoring"], index,
                              ("id", "title", "signal", "status", "hosts"))

        L += ["", "## Where bugs cluster", "",
              "Patterns and components by number of issues: where to look first, and where a plan pays off.", ""]
        pcount = Counter(pt for i in issues for pt in (i.meta.get("patterns") or []))
        L += ["| Pattern | Issues | |", "|---|---|---|"]
        for slug in sorted(self.patterns, key=lambda s: (-pcount[s], s)):
            L.append(f"| [{slug}]({self.link(self.patterns[slug], index)}) | {pcount[slug]} | "
                     f"{str(self.patterns[slug].meta.get('title', '')).replace('|', '/')} |")
        ccount = Counter(c for i in issues for c in (i.meta.get("components") or []))
        L += ["", "| Component | Issues |", "|---|---|"]
        for cid in sorted((c for c in ccount if ccount[c]), key=lambda c: (-ccount[c], c)):
            L.append(f"| [{cid}](#{cid}) | {ccount[cid]} |")

        recent = sorted(issues, key=lambda i: (str(i.meta.get("found")), i.meta.get("id")), reverse=True)[:15]
        L += ["", "## Recent issues", ""]
        L += self.issue_table(recent, index, ("id", "found", "title", "status", "found_by"))

        L += ["", "## Plans", ""]
        if self.plans:
            L += ["| Plan | Title | Status | Issues |", "|---|---|---|---|"]
            for _, p in sorted(self.plans.items()):
                L.append(f"| [{p.meta.get('plan')}]({self.link(p, index)}) | {p.meta.get('title')} | "
                         f"{p.meta.get('status')} | {', '.join(p.meta.get('issues') or [])} |")
        else:
            L.append("_None yet._")

        L += ["", "## Runbooks", "", "One per alert rule (ansible/roles/monitoring/files/alerts.yml).", "",
              "| Alert | Severity | Past occurrences |", "|---|---|---|"]
        for name, p in sorted(self.runbooks.items()):
            n = sum(1 for i in issues if str(i.meta.get("signal")) == name)
            L.append(f"| [{name}]({self.link(p, index)}) | {p.meta.get('severity')} | {n} |")

        L += ["", "## Component map", "",
              "From [components.yml](components.yml): what runs where, and what depends on what "
              "(an arrow points at the dependency).", "", "```mermaid", "flowchart LR"]
        L += self.mermaid()
        L += ["```", "", "## Components", ""]
        for cid in sorted(self.components):
            c = self.components[cid]
            mine = [i for i in issues if cid in (i.meta.get("components") or [])]
            L += [f"### {cid}", "", f"**{c.get('name')}** ({c.get('kind')}"
                  + (f", on {c['host']}" if c.get("host") else "") + f"). {c.get('description', '').strip()}", ""]
            if c.get("roles"):
                L.append("Roles: " + ", ".join(f"`{r}`" for r in c["roles"]) + ".")
            if c.get("docs"):
                L.append("Docs: " + ", ".join(f"`{d}`" for d in c["docs"]) + ".")
            if c.get("depends_on"):
                L.append("Depends on: " + ", ".join(f"[{d}](#{d})" for d in c["depends_on"]) + ".")
            used_by = sorted(k for k, o in self.components.items() if cid in (o.get("depends_on") or []))
            if used_by:
                L.append("Used by: " + ", ".join(f"[{d}](#{d})" for d in used_by) + ".")
            L += ["", *(self.issue_table(mine, index, ("id", "title", "status", "found_by")) if mine
                        else ["_No issues recorded._"]), ""]
        return "\n".join(L).rstrip() + "\n"

    def mermaid(self):
        def mid(cid):
            return "c_" + cid.replace("-", "_")
        out, placed = [], set()
        groups = {}
        for cid, c in sorted(self.components.items()):
            if c.get("kind") == "host":
                continue
            groups.setdefault(c.get("host"), []).append(cid)
        for host in sorted(self.hosts):
            members = groups.get(host, [])
            out.append(f'  subgraph {mid(host)}["{self.components[host].get("name", host)}"]')
            for cid in members:
                out.append(f'    {mid(cid)}["{cid}"]')
                placed.add(cid)
            if not members:
                out.append(f'    {mid(host)}_self["{host}"]')
            out.append("  end")
        for cid, c in sorted(self.components.items()):
            for dep in c.get("depends_on") or []:
                if dep in self.components:
                    out.append(f"  {mid(cid)} --> {mid(dep)}")
        return out

    # -------------------------------------------------------------- freshness
    def stale(self):
        """Generated files that differ from what build would write now."""
        bad = []
        for path, text in sorted(self.render().items()):
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current != text:
                bad.append(f"{path.relative_to(self.repo)}: out of date (run: python3 tools/kb.py build)")
        return bad


def main(argv):
    if len(argv) != 2 or argv[1] not in ("check", "build"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    kb = KB()
    problems = kb.validate()
    if argv[1] == "build":
        for path, text in kb.render().items():
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8", newline="\n")
                print(f"wrote {path.relative_to(kb.repo)}")
    else:
        problems += kb.stale()
    for p in problems:
        print(p)
    print(f"kb: {len(kb.issues)} issues, {len(kb.patterns)} patterns, {len(kb.runbooks)} runbooks, "
          f"{len(kb.plans)} plans, {len(kb.components)} components, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
