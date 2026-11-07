"""Unit tests for tools/kb.py, the knowledge base's checker and generator: a tiny knowledge
base is built in a temporary folder, then broken one way at a time.
Run by tools/check: python3 -m unittest discover -s tests"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import kb  # noqa: E402

COMPONENTS = """\
components:
  - {id: box, name: Box, kind: host, description: A host.}
  - {id: web, name: Web, kind: service, host: box, description: A service., depends_on: [db]}
  - {id: db, name: DB, kind: service, host: box, description: A database.}
"""
ISSUE = """\
---
id: KB-0001
title: Something broke
status: fixed
found_by: monitoring
signal: WebDown
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [box]
components: [web]
patterns: [flaky-thing]
commits: [abc1234]
related: []
---
## Symptom
x
## How it was found
x
## Root cause
x
## Fix
x
## Verification
x
## Prevention
x
"""
PATTERN = """\
---
pattern: flaky-thing
title: Things are flaky
components: [web]
---
## What happens
## How to spot it
## How to fix
## How to prevent
<!-- kb:generated:start -->
<!-- kb:generated:end -->
"""
RUNBOOK = """\
---
alert: WebDown
severity: critical
components: [web]
---
## What it means
## First five minutes
## Common causes
## Escalate / fix
<!-- kb:generated:start -->
<!-- kb:generated:end -->
"""
ALERTS = f"""\
groups:
  - name: g
    rules:
      - alert: WebDown
        expr: up == 0
        annotations:
          runbook_url: {kb.RUNBOOK_BASE}WebDown.md
"""


class KnowledgeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.kb = self.repo / "docs" / "kb"
        self.page("components.yml", COMPONENTS)
        self.page("issues/KB-0001-something-broke.md", ISSUE)
        self.page("patterns/flaky-thing.md", PATTERN)
        self.page("runbooks/WebDown.md", RUNBOOK)
        self.write("ansible/roles/monitoring/files/alerts.yml", ALERTS)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")

    def page(self, rel, text):
        """A page in the temporary knowledge base (rel is relative to its docs/kb)."""
        self.write(str(Path("docs", "kb", rel)), text)

    def problems(self):
        return kb.KB(self.repo).validate()

    def assertProblem(self, fragment):
        found = self.problems()
        self.assertTrue(any(fragment in p for p in found), f"no problem mentioning {fragment!r} in {found}")

    def test_a_valid_knowledge_base_has_no_problems(self):
        self.assertEqual(self.problems(), [])

    def test_build_then_nothing_is_stale_and_build_is_deterministic(self):
        first = kb.KB(self.repo).render()
        for path, text in first.items():
            path.write_text(text, encoding="utf-8")
        self.assertEqual(kb.KB(self.repo).stale(), [])
        self.assertEqual(kb.KB(self.repo).render(), first)

    def test_generated_blocks_list_backlinks(self):
        out = kb.KB(self.repo).render()
        pattern = out[self.kb / "patterns" / "flaky-thing.md"]
        self.assertIn("[KB-0001](../issues/KB-0001-something-broke.md)", pattern)
        self.assertIn("KB-0001", out[self.kb / "runbooks" / "WebDown.md"])
        self.assertIn("c_web --> c_db", out[self.kb / "INDEX.md"])

    def test_a_hand_edit_inside_a_generated_block_is_stale(self):
        for path, text in kb.KB(self.repo).render().items():
            path.write_text(text, encoding="utf-8")
        page = self.kb / "patterns" / "flaky-thing.md"
        page.write_text(page.read_text(encoding="utf-8").replace("Issues with this pattern", "edited"), encoding="utf-8")
        self.assertTrue(any("flaky-thing.md: out of date" in s for s in kb.KB(self.repo).stale()))

    def test_unknown_values_and_references(self):
        self.page("issues/KB-0001-something-broke.md",
                   ISSUE.replace("found_by: monitoring", "found_by: luck").replace("components: [web]", "components: [nope]")
                   .replace("patterns: [flaky-thing]", "patterns: [missing]").replace("related: []", "related: [KB-0099]"))
        found = "\n".join(self.problems())
        for fragment in ("found_by must be one of", "unknown component 'nope'", "unknown pattern 'missing'",
                         "unknown issue 'KB-0099'"):
            self.assertIn(fragment, found)

    def test_id_must_match_file_name(self):
        self.page("issues/KB-0001-something-broke.md", ISSUE.replace("id: KB-0001", "id: KB-0002"))
        self.assertProblem("doesn't match the file name")

    def test_fixed_needs_resolved_and_open_must_not_have_it(self):
        self.page("issues/KB-0001-something-broke.md", ISSUE.replace("resolved: 2026-11-07\n", ""))
        self.assertProblem("needs resolved")
        self.page("issues/KB-0001-something-broke.md", ISSUE.replace("status: fixed", "status: open"))
        self.assertProblem("must not have resolved")

    def test_sections_in_order(self):
        self.page("issues/KB-0001-something-broke.md", ISSUE.replace("## Fix\nx\n", ""))
        self.assertProblem("body needs the sections")

    def test_every_alert_needs_a_runbook_and_its_url(self):
        self.write("ansible/roles/monitoring/files/alerts.yml",
                   ALERTS + "      - alert: DiskFull\n        expr: vector(1)\n")
        found = "\n".join(self.problems())
        self.assertIn("alert DiskFull has no runbook", found)
        self.assertIn("alert DiskFull needs annotation runbook_url", found)

    def test_a_runbook_without_an_alert_is_an_orphan(self):
        self.page("runbooks/OldAlert.md", RUNBOOK.replace("alert: WebDown", "alert: OldAlert"))
        self.assertProblem("no alert rule named OldAlert")

    def test_dependency_cycles_and_unknown_dependencies(self):
        self.page("components.yml", COMPONENTS.replace("description: A database.}",
                                                                "description: A database., depends_on: [web, ghost]}"))
        found = "\n".join(self.problems())
        self.assertIn("dependency cycle", found)
        self.assertIn("depends_on 'ghost' is not a component", found)

    def test_hosts_must_be_host_components(self):
        self.page("issues/KB-0001-something-broke.md", ISSUE.replace("hosts: [box]", "hosts: [web]"))
        self.assertProblem("unknown host 'web'")

    def test_page_without_front_matter(self):
        self.page("issues/KB-0003-bare.md", "# just text\n")
        self.assertProblem("no front matter")


if __name__ == "__main__":
    unittest.main()
