#!/usr/bin/python
"""Ansible module, runs on dc01: make the lab's AD accounts and DHCP reservations match
its inventory. Called by roles/dc_identity (ansible/identity.yml), which `lab` runs.

Why a module and not tasks: this is set arithmetic over AD objects (which computers
exist, which should, which groups and owners they have) that Ansible has no Samba
modules for. As tasks it was a page of shell, regex and Jinja; here it's plain Python
that supports --check, reports exactly what it changed, and keeps passwords out of
every log (no_log on those parameters).

Everything is scoped: only hosts in `scope` are touched ("all" = every workstation
account and reservation that exists or should exist).
"""
import os
import re
import subprocess
import tempfile

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = r"""
module: lab_dc_identity
short_description: Lab workstations' AD accounts and DHCP reservations, from the inventory
options:
  phase: {description: "present (before VMs are created) or cleanup (after VMs are destroyed)", required: true, type: str}
  scope: {description: '"all" or a list of host names', required: true, type: raw}
  desired: {description: "{host: {vmid, mac, ip, role, owner?}}", required: true, type: dict}
  removed: {description: "{host: spec} of guest machines being deleted", type: dict, default: {}}
  otp: {description: "{host: one-time join password} to set on computer accounts", type: dict, default: {}}
  passwords: {description: "{owner: password} for guest accounts that must be created", type: dict, default: {}}
  base_dn: {required: true, type: str}
  hosts_dir: {description: "dnsmasq dhcp-hostsdir: one reservation file per host", type: str, default: /etc/dnsmasq-hosts.d}
  leases: {type: str, default: /var/lib/misc/dnsmasq.leases}
  interface: {description: "DHCP interface, for dhcp_release", type: str, default: ens18}
"""

SAM = "/var/lib/samba/private/sam.ldb"
WS_OU = "OU=Workstations,OU=Lab"      # computer accounts (pre-staged; the machine joins with its OTP)
GUEST_OU = "OU=Guests,OU=Lab"         # owners of guest machines; deliberately in no role group
STAFF_OU = "OU=Users,OU=Lab"          # the studio's people (roles/ad_people): may own machines, never deleted here


class Dc:
    def __init__(self, module, base_dn):
        self.m, self.base, self.actions = module, base_dn, []

    # ---- reading (always runs, also in --check)
    def search(self, base, flt, *attrs, scope="sub"):
        """ldbsearch -> [{attr: [values]}], with LDIF line folding undone."""
        r = subprocess.run(["ldbsearch", "-H", SAM, "-s", scope, "-b", base, flt, *attrs],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return []                      # e.g. the OU doesn't exist yet
        text = re.sub(r"\n ", "", r.stdout)
        found = []
        for block in text.split("\n\n"):
            obj = {}
            for line in block.splitlines():
                if line.startswith("#") or ": " not in line:
                    continue
                key, value = line.split(": ", 1)
                obj.setdefault(key.rstrip(":").lower(), []).append(value)
            if "dn" in obj:
                found.append(obj)
        return found

    def computers(self):
        """{host: {dn, groups, managedby}} for computer accounts in OU=Workstations."""
        found = {}
        for o in self.search(f"{WS_OU},{self.base}", "(objectClass=computer)", "sAMAccountName", "memberOf", "managedBy"):
            name = o.get("samaccountname", [""])[0].rstrip("$").lower()
            groups = [re.match(r"CN=([^,]+)", g).group(1) for g in o.get("memberof", [])]
            found[name] = {"dn": o["dn"][0], "groups": groups, "managedby": (o.get("managedby") or [None])[0]}
        return found

    def users(self, ou):
        """{name: dn} for user accounts in an OU."""
        return {o["samaccountname"][0].lower(): o["dn"][0]
                for o in self.search(f"{ou},{self.base}", "(objectClass=user)", "sAMAccountName")
                if "samaccountname" in o}

    def guest_users(self):
        return self.users(GUEST_OU)

    def ou_exists(self, ou):
        return bool(self.search(f"{ou},{self.base}", "(objectClass=*)", "dn", scope="base"))

    # ---- changing (skipped in --check, always recorded)
    def do(self, what, cmd, stdin=None):
        self.actions.append(what)
        if self.m.check_mode:
            return
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
        if r.returncode != 0:
            self.m.fail_json(msg=f"{what}: {r.stderr.strip() or r.stdout.strip()}", actions=self.actions)

    def modify(self, what, ldif):
        """ldbmodify with an LDIF change (from a private temporary file)."""
        self.actions.append(what)
        if self.m.check_mode:
            return
        with tempfile.NamedTemporaryFile("w", suffix=".ldif") as f:
            f.write(ldif)
            f.flush()
            r = subprocess.run(["ldbmodify", "-H", SAM, f.name], capture_output=True, text=True)
        if r.returncode != 0:
            self.m.fail_json(msg=f"{what}: {r.stderr.strip()}", actions=self.actions)


def read(path):
    with open(path) as f:
        return f.read()


def reservation(spec, host):
    """One dhcp-hostsdir file: MAC -> IP -> name (dnsmasq's dhcp-host syntax, without
    the option name). dnsmasq's DHCP hook registers the name in AD DNS."""
    return f"{spec['mac']},{spec['ip']},{host}\n"


def main():
    m = AnsibleModule(argument_spec=dict(
        phase=dict(type="str", required=True, choices=["present", "cleanup"]),
        scope=dict(type="raw", required=True),
        desired=dict(type="dict", required=True),
        removed=dict(type="dict", default={}),
        otp=dict(type="dict", default={}, no_log=True),
        passwords=dict(type="dict", default={}, no_log=True),
        base_dn=dict(type="str", required=True),
        hosts_dir=dict(type="str", default="/etc/dnsmasq-hosts.d"),
        leases=dict(type="str", default="/var/lib/misc/dnsmasq.leases"),
        interface=dict(type="str", default="ens18"),
    ), supports_check_mode=True)
    p = m.params
    dc, desired, hosts_dir = Dc(m, p["base_dn"]), p["desired"], p["hosts_dir"]
    computers = dc.computers()
    files = {f for f in os.listdir(hosts_dir) if re.fullmatch(r"ws[a-z0-9-]+", f)} if os.path.isdir(hosts_dir) else set()
    everything = set(desired) | set(computers) | files
    scope = everything if p["scope"] == "all" else set(p["scope"])
    reload_dhcp, releases = False, []

    if p["phase"] == "present":
        if any(desired[h].get("owner") for h in scope & set(desired)) and not dc.ou_exists(GUEST_OU):
            dc.do("create OU=Guests", ["samba-tool", "ou", "create", GUEST_OU])
        # Owners: visitors (OU=Guests, created below) or staff, whose accounts already exist
        staff = dc.users(STAFF_OU)
        users = {**dc.guest_users(), **staff}
        role_groups = {o["cn"][0] for o in dc.search(p["base_dn"], "(&(objectClass=group)(cn=role-*))", "cn")}
        # A new catalog/ entry needs its AD group; the group is how a machine learns its role
        for role in sorted({desired[h]["role"] for h in scope & set(desired)}):
            if f"role-{role}" not in role_groups:
                dc.do(f"create group role-{role}", ["samba-tool", "group", "add", f"role-{role}",
                                                    "--groupou=OU=Groups,OU=Lab"])
                role_groups.add(f"role-{role}")
        for host in sorted(scope & set(desired)):
            spec = desired[host]
            if host not in computers:
                dc.do(f"add computer {host}", ["samba-tool", "computer", "add", host, f"--computerou={WS_OU}"])
                computers[host] = {"dn": f"CN={host.upper()},{WS_OU},{p['base_dn']}", "groups": [], "managedby": None}
            # Exactly one role group: the machine reads it to know what it is (roles/ad_join)
            want = f"role-{spec['role']}"
            if want not in computers[host]["groups"]:
                dc.do(f"{host}: add to {want}", ["samba-tool", "group", "addmembers", want, f"{host}$"])
            for g in set(computers[host]["groups"]) & set(role_groups) - {want}:
                dc.do(f"{host}: remove from {g}", ["samba-tool", "group", "removemembers", g, f"{host}$"])
            # Guest machines: the owner's account, and managedBy pointing at it
            owner = spec.get("owner")
            if owner and owner not in users and spec.get("staff"):
                m.fail_json(msg=f"{host}: owner {owner} has no account in {STAFF_OU}", actions=dc.actions)
            if owner and owner not in users:
                n = int(spec["vmid"]) - 130         # RFC2307 IDs from the guest slot: unique, stable
                dc.do(f"create guest account {owner}", [
                    "samba-tool", "user", "create", owner, p["passwords"].get(owner) or os.urandom(12).hex() + "Aa1",
                    f"--userou={GUEST_OU}", f"--given-name={owner}", "--surname=Guest", "--use-username-as-cn",
                    "--nis-domain=lab", f"--uid-number={20100 + n}", "--gid-number=10000",
                    f"--unix-home=/home/{owner}", "--login-shell=/bin/bash"])
                users[owner] = f"CN={owner},{GUEST_OU},{p['base_dn']}"
            want_owner = users.get(owner) if owner else None
            if computers[host]["managedby"] != want_owner:
                change = f"replace: managedBy\nmanagedBy: {want_owner}" if want_owner else "delete: managedBy"
                dc.modify(f"{host}: owner {owner or 'none'}",
                          f"dn: {computers[host]['dn']}\nchangetype: modify\n{change}\n")
            # DHCP reservation: new files are read at once; a changed one needs a SIGHUP
            path, content = os.path.join(hosts_dir, host), reservation(spec, host)
            current = read(path) if os.path.exists(path) else None
            if current != content:
                dc.actions.append(f"{host}: DHCP reservation {spec['mac']} -> {spec['ip']}")
                if not m.check_mode:
                    with open(path, "w") as f:
                        f.write(content)
                reload_dhcp |= current is not None
        for host in sorted(p["otp"]):
            # Resets the machine password: only for machines that are about to be
            # (re)built, which then join with it once (roles/ad_join)
            dc.do(f"{host}: new one-time join password", ["samba-tool", "user", "setpassword", f"{host}$",
                                                           f"--newpassword={p['otp'][host]}"])

    else:   # cleanup: whatever in scope is no longer desired
        for host in sorted(scope - set(desired)):
            if host in computers:
                dc.do(f"delete computer {host}", ["samba-tool", "computer", "delete", host])
            path = os.path.join(hosts_dir, host)
            if os.path.exists(path):
                mac, ip = read(path).strip().split(",")[:2]
                releases.append((mac.lower(), ip))
                dc.actions.append(f"{host}: delete DHCP reservation")
                if not m.check_mode:
                    os.remove(path)
                reload_dhcp = True
        owners = {s.get("owner") for s in desired.values()} - {None}
        users = dc.guest_users()
        if p["scope"] == "all":
            gone = set(users) - owners
        else:
            gone = {p["removed"][h]["owner"] for h in scope if h in p["removed"]} & set(users) - owners
        for user in sorted(gone):
            dc.do(f"delete guest account {user}", ["samba-tool", "user", "delete", user])

    if reload_dhcp:
        # dnsmasq keeps a deleted or changed reservation until it gets a SIGHUP
        dc.do("reload DHCP reservations", ["systemctl", "kill", "--signal=HUP", "dnsmasq"])
    if releases and os.path.exists(p["leases"]):
        # A removed machine's lease would live on for hours, and with it its DNS records.
        # Releasing it makes dnsmasq fire its "del" event now; with the reservation gone,
        # the hook (dhcp-dns-update) deletes the A and PTR records.
        for line in read(p["leases"]).splitlines():
            f = line.split()
            if len(f) >= 4 and (f[1].lower(), f[2]) in releases:
                cmd = ["dhcp_release", p["interface"], f[2], f[1]] + ([f[4]] if len(f) > 4 and f[4] != "*" else [])
                dc.do(f"release lease {f[2]} ({f[3]})", cmd)

    m.exit_json(changed=bool(dc.actions), actions=dc.actions)


if __name__ == "__main__":
    main()
