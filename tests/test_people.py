"""Unit tests for the welcome page's form handling (lablib: match_team, check_person,
password_problems): what someone types from memory becomes what they meant, and every
change is reported. Made-up people only: no real names belong in this repository.
Run by tools/check: python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ.setdefault("LAB_STATE", tempfile.mkdtemp())
sys.path.insert(0, str(REPO / "ansible" / "roles" / "runner" / "files"))
import lablib as L  # noqa: E402

TEAMS = L.teams(REPO)


class Teams(unittest.TestCase):
    def test_typos_aliases_and_titles(self):
        for typed, team in [("Animation", "animation"), ("animatoin", "animation"), ("Cinematics", "animation"),
                            ("sound design", "audio"), ("SFX", "audio"), ("Visual Efects", "vfx"),
                            ("enviroment art", "environment"), ("tech producer", "production"),
                            ("Senior Cinematic Animator", "animation"), ("Lead Writer", "narrative"),
                            ("infrastucture", "it"), ("Gameplay programming", "engineering"),
                            ("Game desing", "design")]:
            self.assertEqual(L.match_team(typed, TEAMS), team, typed)

    def test_nothing_close(self):
        for typed in ("", "   ", "zzzz", "catering"):
            self.assertIsNone(L.match_team(typed, TEAMS), typed)


class People(unittest.TestCase):
    def test_tidies_and_reports(self):
        clean, corrections, problems = L.check_person(
            {"username": "pvandam", "given": " pim ", "surname": "VAN DAM", "title": "sound designer", "team": "Audoi"}, TEAMS)
        self.assertEqual(problems, [])
        self.assertEqual((clean["given"], clean["surname"], clean["title"], clean["team"]),
                         ("Pim", "van Dam", "Sound Designer", "audio"))
        self.assertEqual({c["field"] for c in corrections}, {"given", "surname", "title", "team"})

    def test_mixed_case_kept(self):
        clean, corrections, _ = L.check_person(
            {"username": "kmacbride", "given": "Kim", "surname": "MacBride", "title": "Animator", "team": "Animation"}, TEAMS)
        self.assertEqual(clean["surname"], "MacBride")
        self.assertEqual(corrections, [])

    def test_team_from_title_and_username_pattern(self):
        clean, _, problems = L.check_person(
            {"username": "zbogus", "given": "Zoë", "surname": "Lefèbre", "title": "Character Animator", "team": ""}, TEAMS)
        self.assertEqual(clean["team"], "animation")
        self.assertTrue(any("zlefebre" in p for p in problems), problems)

    def test_expected_username(self):
        self.assertEqual(L.expected_username("Pim", "van Dam"), "pvandam")
        self.assertEqual(L.expected_username("Zoë", "Lefèbre"), "zlefebre")


class Titles(unittest.TestCase):
    TITLES = L.known_titles(TEAMS, {"x": {"title": "Lead Rigger", "team": "animation"}})

    def test_known_titles_from_teams_and_ad(self):
        self.assertEqual(self.TITLES["Sound Designer"], "audio")
        self.assertEqual(self.TITLES["Lead Rigger"], "animation")          # only in AD

    def test_typos_corrected_to_the_known_title(self):
        for typed, title in [("Sound Desinger", "Sound Designer"), ("sound designer", "Sound Designer"),
                             ("Gamplay Programer", "Gameplay Programmer"), ("lead rigger", "Lead Rigger")]:
            self.assertEqual(L.match_title(typed, self.TITLES), title, typed)
        for typed in ("", "Catering Manager"):
            self.assertIsNone(L.match_title(typed, self.TITLES), typed)

    def test_check_person_corrects_title_and_takes_its_team(self):
        clean, corrections, problems = L.check_person(
            {"username": "nvandam", "given": "Nina", "surname": "van Dam", "title": "Sound Desinger", "team": ""},
            TEAMS, self.TITLES)
        self.assertEqual((clean["title"], clean["team"], problems), ("Sound Designer", "audio", []))
        self.assertIn({"field": "title", "typed": "Sound Desinger", "now": "Sound Designer"}, corrections)
        # a title nobody has yet is kept as typed
        clean, _, _ = L.check_person({"username": "nvandam", "given": "Nina", "surname": "van Dam",
                                      "title": "Audio Wrangler", "team": "Audio"}, TEAMS, self.TITLES)
        self.assertEqual(clean["title"], "Audio Wrangler")


class Passwords(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(L.password_problems("Correct-Horse-9", "pvandam", ("Pim", "van Dam")), [])
        self.assertTrue(L.password_problems("short1A"))
        self.assertTrue(L.password_problems("alllowercase"))
        self.assertTrue(L.password_problems("Pvandam-2026!", "pvandam"))


if __name__ == "__main__":
    unittest.main()
