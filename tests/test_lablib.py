"""Unit tests for lablib (ansible/roles/runner/files/lablib.py): the inventory rules,
the address plan, and the parsers for OpenTofu plans and nginx's lab-events log.
Run by tools/check: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE = tempfile.mkdtemp()
os.environ["LAB_STATE"] = STATE            # before the import: lablib reads it once
sys.path.insert(0, str(REPO / "ansible" / "roles" / "runner" / "files"))
import lablib as L  # noqa: E402

CFG = L.settings(REPO)
CAT = L.catalog(REPO)


def ws(vmid, role="artist", **extra):
    return {"vmid": vmid, **L.address_for(vmid, CFG), "role": role, **extra}


class Inventory(unittest.TestCase):
    def test_the_repository_inventory_is_valid(self):
        self.assertEqual(L.validate(L.fleet(REPO), CAT, CFG), [])

    def test_address_plan(self):
        self.assertEqual(L.address_for(123, CFG), {"ip": "10.10.10.23", "mac": "BC:24:11:00:00:23"})
        self.assertEqual(L.address_for(109, CFG)["mac"], "BC:24:11:00:00:09")

    def test_good_machine(self):
        self.assertEqual(L.validate({"ws05": ws(125)}, CAT, CFG), [])

    def test_address_must_match_vmid(self):
        bad = ws(125) | {"ip": "10.10.10.99"}
        self.assertIn("should be 10.10.10.25", " ".join(L.validate({"ws05": bad}, CAT, CFG)))

    def test_vmid_ranges_by_kind(self):
        self.assertTrue(L.validate({"ws05": ws(131)}, CAT, CFG))                  # guest range
        self.assertEqual(L.validate({"ws-ann": ws(131, kind="guest", owner="ann")}, CAT, CFG), [])
        self.assertTrue(L.validate({"ws-ann": ws(125, kind="guest", owner="ann")}, CAT, CFG))

    def test_duplicates(self):
        problems = L.validate({"ws05": ws(125), "ws06": ws(125)}, CAT, CFG)
        self.assertTrue(any("also used by" in p for p in problems))

    def test_unknown_role_and_bad_names(self):
        self.assertTrue(L.validate({"ws05": ws(125, role="wizard")}, CAT, CFG))
        self.assertTrue(L.validate({"dc01": ws(125)}, CAT, CFG))
        self.assertTrue(L.validate({"WS05": ws(125)}, CAT, CFG))

    def test_guests_need_an_owner(self):
        self.assertTrue(L.validate({"ws-x": ws(131, kind="guest")}, CAT, CFG))


class Records(unittest.TestCase):
    def setUp(self):
        L.GUESTS.mkdir(parents=True, exist_ok=True)
        for p in L.GUESTS.glob("*.json"):
            p.unlink()

    def test_desired_skips_removed_and_rejected(self):
        for host, state, extra in (("ws-ann", "ready", {}), ("ws-bob", "removing", {}),
                                   ("ws-cat", "failed", {"rejected": True})):
            L.write_json(L.guest_path(host), {"host": host, "state": state, "owner": host[3:],
                                              **ws(131), "role": "artist", **extra})
        want = L.desired(REPO)
        self.assertIn("ws-ann", want)
        self.assertNotIn("ws-bob", want)
        self.assertNotIn("ws-cat", want)
        self.assertIn("ws03", want)                           # the fleet is always there

    def test_phases_are_recorded_once(self):
        L.write_json(L.guest_path("ws-ann"), {"host": "ws-ann", "phases": {}})
        first = L.guest_phase("ws-ann", "identity")["phases"]["identity"]
        again = L.guest_phase("ws-ann", "identity", state="building")
        self.assertEqual(again["phases"]["identity"], first)
        self.assertEqual(again["state"], "building")

    def test_free_guest_vmid(self):
        self.assertEqual(L.free_guest_vmid(CFG, {131, 132}), 133)
        self.assertIsNone(L.free_guest_vmid(CFG, set(range(131, 140))))


class Parsers(unittest.TestCase):
    def test_plan_changes(self):
        plan = {"resource_changes": [
            {"address": 'module.workstation["ws03"].proxmox_virtual_environment_vm.this',
             "type": "proxmox_virtual_environment_vm", "change": {"actions": ["delete", "create"]}},
            {"address": 'module.workstation["ws04"].proxmox_virtual_environment_vm.this',
             "type": "proxmox_virtual_environment_vm", "change": {"actions": ["delete"]}},
            {"address": 'module.workstation["ws05"].proxmox_virtual_environment_vm.this',
             "type": "proxmox_virtual_environment_vm", "change": {"actions": ["create"]}},
            {"address": 'module.workstation["ws06"].proxmox_virtual_environment_vm.this',
             "type": "proxmox_virtual_environment_vm", "change": {"actions": ["no-op"]}},
        ]}
        self.assertEqual(L.plan_changes(plan), {"ws03": "replace", "ws04": "delete", "ws05": "create"})

    def test_tofu_progress_lines(self):
        m = L.TOFU_LINE.search('module.workstation["ws03"].proxmox_virtual_environment_vm.this: Destruction complete after 4s')
        self.assertEqual((m.group("host"), m.group("what")), ("ws03", "Destruction complete"))
        m = L.TOFU_LINE.search("module.workstation.proxmox_virtual_environment_vm.this: Creation complete after 31s [id=132]")
        self.assertEqual((m.group("host"), m.group("what")), (None, "Creation complete"))

    def test_lab_events_log(self):
        line = json.dumps({"time": "2026-11-07T12:00:00+01:00", "ip": "10.10.10.32", "uri": "/otp/ws-ann", "status": 200})
        self.assertEqual(L.parse_event(line)["uri"], "/otp/ws-ann")
        self.assertIsNone(L.parse_event("not json"))


if __name__ == "__main__":
    unittest.main()
