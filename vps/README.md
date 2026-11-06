# VPS (Contabo, Ubuntu 24.04): the lab's front door

The lab sits on a home network with no inbound access. A small VPS is its public edge:
it terminates HTTPS for the public names, asks visitors to sign in, and passes requests
through a WireGuard tunnel that **pve01 dials out** to.

| Name | What | Path |
|---|---|---|
| `lab.radicallydecent.com` | self-service portal + browser terminal | VPS (sign-in gate) → tunnel → pve01 relay (TCP) → mgmt01:8443 |
| `pve.radicallydecent.com` | Proxmox UI | VPS (sign-in gate) → tunnel → pve01:8006 |
| `acme-ns.radicallydecent.com` | acme-dns update API (`/update` only) | VPS |

Every hop is HTTPS with a **verified** Let's Encrypt certificate: the VPS checks
mgmt01's and pve01's certificates for these names before forwarding anything
(`proxy_ssl_verify_depth 2`; nginx's default of 1 can't verify a Let's Encrypt chain).
Inside the lab, AD DNS resolves `lab.radicallydecent.com` to mgmt01, so lab machines use
the same name and certificate.

## Sign-in gate: oauth2-proxy

`lab.` and `pve.` are private. nginx asks [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/)
v7.15.6 (`oauth2-proxy/`) about every request (`auth_request`, `nginx-lab-gate.conf`);
without a session it redirects to a sign-in page at `/oauth2/sign_in`.

- **Why oauth2-proxy:** its sign-in and error pages are templates that can be replaced
  completely (`oauth2-proxy/templates/`), so they match the portal. Authelia's sign-in
  page offers only built-in themes. Browser Basic auth, used before, can't be styled at
  all.
- **Local accounts only:** a bcrypt htpasswd file (`/etc/oauth2-proxy/users.htpasswd`),
  currently one lab access account. oauth2-proxy requires an OAuth provider to be
  configured; this one is a placeholder nobody can use, and nginx answers 404 for its
  start URL.
- **One session for both sites:** a 12-hour, Secure, HttpOnly cookie for
  `.radicallydecent.com`; sign-in redirects only go back to `.radicallydecent.com`.
- **Password guessing:** 5 attempts a minute per address (nginx `limit_req`).
- The portal's admin page has its own sign-in after this one, with an AD account.

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
record**. The accounts live root-only where they're used and are never committed.
Registration is only possible on the VPS itself (the API listens on 127.0.0.1; nginx
publishes only `POST /update`).

| Certificate | Issued on | Client | Account |
|---|---|---|---|
| `lab.radicallydecent.com` | VPS and mgmt01 | certbot + `mgmt01/portal/certbot-acme-dns-hook` | `/etc/acme-dns/accounts/`, `/etc/lab-portal/acme-dns/` |
| `pve.radicallydecent.com` | VPS and pve01 | certbot; Proxmox's ACME client (`acmedns` plugin) | `/etc/acme-dns/accounts/`, `/root/acme-dns/` |
| `acme-ns.radicallydecent.com` | VPS | certbot | `/etc/acme-dns/accounts/` |
| `dc01.lab.radicallydecent.com` | dc01 (LDAPS) | certbot; `dc01/samba-tls-deploy` installs it and restarts Samba | `/etc/acme-dns-client/` |

`dc01.lab.radicallydecent.com` exists only inside the lab; Let's Encrypt never needs to
reach it, only its challenge record. certbot timers and Proxmox renew everything. ACME
contact everywhere: jesse@radicallydecent.com.

## Files here

- `nginx-*.radicallydecent.com`: the three sites (`/etc/nginx/sites-available/`);
  `nginx-lab-gate.conf`: the gate snippet (`/etc/nginx/snippets/lab-gate.conf`).
  The main radicallydecent.com website on the same VPS is not part of this repo.
- `oauth2-proxy/`: its config, systemd unit and page templates (`/etc/oauth2-proxy/`).
- `acme-dns.cfg`, `acme-dns.service`: `/etc/acme-dns/config.cfg`, the systemd unit.
- SSH: keys only, no root login (`/etc/ssh/sshd_config.d/10-hardening.conf`).
