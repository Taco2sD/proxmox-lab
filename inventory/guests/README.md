# Guest machines

One file per workstation requested through the self-service portal, written and
committed by the portal (see docs/self-service.md). Format:

```yaml
ws-alice: { vmid: 131, mac: "BC:24:11:00:00:31", ip: 10.10.10.31, role: artist, owner: alice }
```

Deleting a file and running `lab apply` + `lab prune` removes that machine.
