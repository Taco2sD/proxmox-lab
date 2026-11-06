# VPS (Contabo, Ubuntu 24.04): the lab's front door

The lab sits on a home network with no inbound access. A small VPS is its public edge:
it terminates HTTPS for the public names, asks for the demo password, and passes
requests through a WireGuard tunnel that **pve01 dials out** to.

| Name | What | Path |
|---|---|---|
| `lab.radicallydecent.com` | self-service portal + browser terminal | VPS → tunnel → pve01 relay (TCP) → mgmt01:8443 |
| `pve.radicallydecent.com` | Proxmox UI | VPS → tunnel → pve01:8006 |
| `acme-ns.radicallydecent.com` | acme-dns update API (`/update` only) | VPS |

Every hop is HTTPS with a **verified** Let's Encrypt certificate: the VPS checks
mgmt01's and pve01's certificates for these names before forwarding anything. Inside the
lab, AD DNS resolves `lab.radicallydecent.com` to mgmt01, so lab machines use the same
name and certificate.

## Certificates without the registrar key: acme-dns

Machines inside the lab can't be reached for Let's Encrypt's HTTP check, so every lab
certificate uses the DNS-01 check. Instead of giving lab machines the Porkbun API key
(which controls the whole domain, mail included), the VPS runs
[acme-dns](https://github.com/joohoi/acme-dns) v2.0.2 (`acme-dns.cfg`,
`acme-dns.service`), authoritative for `acme.radicallydecent.com` only:

```text
_acme-challenge.lab.radicallydecent.com  CNAME  <uuid>.acme.radicallydecent.com
acme.radicallydecent.com                 NS     acme-ns.radicallydecent.com
```

Each certificate name has an acme-dns account that can change **only its own TXT
record**. The accounts live root-only on the VPS (`/etc/acme-dns/accounts/`), mgmt01
(`/etc/lab-portal/acme-dns/`) and pve01 (`/root/acme-dns/`); they are never committed.
Registration is only possible on the VPS itself (the API listens on 127.0.0.1; nginx
publishes only `POST /update`).

- **VPS and mgmt01:** certbot with `mgmt01/portal/certbot-acme-dns-hook` as the manual
  auth hook; `certbot.timer` renews.
- **pve01:** Proxmox's built-in ACME client with its `acmedns` DNS plugin; Proxmox renews.
- ACME contact everywhere: jesse@radicallydecent.com.

## Files here

- `nginx-*.radicallydecent.com`: the three sites (`/etc/nginx/sites-available/`).
  The main radicallydecent.com website on the same VPS is not part of this repo.
- `acme-dns.cfg`, `acme-dns.service`: `/etc/acme-dns/config.cfg`, the systemd unit.
- SSH: keys only, no root login (`/etc/ssh/sshd_config.d/10-hardening.conf`).
