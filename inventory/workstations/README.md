# The fleet

One file per long-lived workstation; the file name is the machine's name. This
directory is the whole list: there is no index file to keep in step with it.

```yaml
# ws05.yml, a new file next to this README
vmid: 125
mac: "BC:24:11:00:00:25"
ip: 10.10.10.25
role: artist          # an entry in catalog/
```

- **Add a machine:** add a file and push to `main`. When the checks pass, CI moves
  `stable` forward and mgmt01's reconciler builds it within a few minutes: AD computer
  account in `role-<role>`, DHCP reservation, a clone of the golden image, domain join.
- **Remove a machine:** delete its file (or use the portal's admin page, which makes
  that commit for you). Destroying a VM needs an admin's approval on the admin page;
  a delete started from the admin page counts as one.
- **Rules** (checked by `tools/validate_inventory.py`, in CI and before every `lab`
  run): VM IDs in the fleet range of `ansible/group_vars/all.yml`, IP and MAC derived
  from the VM ID (VM 1NN → 10.10.10.NN, BC:24:11:00:00:NN), nothing used twice, and
  the role must exist in `catalog/`.

Machines requested through the self-service portal are not here: they're runtime
records on mgmt01 (see `docs/self-service.md`), not code.
