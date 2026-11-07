# Things that broke, and why

Most of the learning was here. Each of these is fixed in the code.

| Symptom | Cause | Fix |
|---|---|---|
| UEFI VM has no network boot option at all | Since the 2024 PixieFail fixes, EDK2's network stack won't start without an entropy source; the default Proxmox CPU type doesn't expose RDRAND | Give VMs a virtio RNG (`--rng0 source=/dev/urandom`) |
| Netboot installer: "No space left on device" even at 7 GB RAM | Ubuntu's `url=` netboot downloads the ISO into the initramfs rootfs, a tmpfs capped at 40% of RAM on this kernel | `initramfs_options=size=90%` on the installer's kernel command line (kernel 7.0+) |
| apt: "Release file is not valid yet" after the host slept | Nested VMs froze with the hypervisor and woke ~5 h behind; chrony's default `makestep 1 3` only steps the clock at startup | `makestep 1 -1` everywhere |
| `ansible-pull` fails to clone | The first in-lab git server was plain nginx ("dumb HTTP"), which can't serve shallow clones | `--full` at first; now workstations pull from GitHub, which can |
| DHCP server's DNS updates REFUSED | AD DNS name objects are owned by whoever created them, including empty "tombstoned" ones left by earlier client self-registration | Single writer (the DHCP service account); clients don't register |
| Every Ansible run "changed" sssd.conf and restarted SSSD | `sssd.service` resets `/etc/sssd` to `root:sssd`, group-readable, on every start; the role wrote `0600` | Write `root:sssd 0640`, matching what the service enforces |
| First boot and later runs disagreed about the machine's AD groups | Refreshing local facts mid-play is unreliable in ansible-core 2.20, and the old fact names are deprecated | The role runs the AD lookup directly and stores it in one variable |
| Reimaged VM reinstalled itself 8 times | The first reimage script used `qm disk unlink`, which also removes the disk from the boot order, so the VM kept PXE-booting | The VM definition sets its boot order explicitly |
| Installer: kernel panic, "System is deadlocked on memory" | A ballooning range let Proxmox shrink the VM mid-install; the installer's RAM-held ISO can't be given back | Fixed memory (no balloon range). Workstations no longer run the installer at all (golden image) |
| A reimage held the OpenTofu state lock for 15 minutes | The provider waits up to 15 minutes for the guest agent; an installing or crashed VM has none | `agent.timeout = "30s"`, and `stop_on_destroy` so a crashed VM is powered off instead of waited on |
| Configuration runs failed after an SSH policy change | Ubuntu starts `ssh.service` on demand (`ssh.socket`), so `systemctl reload ssh` fails while it isn't running | `systemctl try-reload-or-restart ssh` |
| The first portal-built machine stopped at "An error occurred" | The old shell `lab` found new machines with `comm`, comparing a locale-sorted list with a Python-sorted one; `ws-tester` sorted differently in each, so it never got a one-time password | Byte-order sort at the time; `lab` is Python now and works from the OpenTofu plan itself |
| Browser terminal filled with `start=…;machineid=…` on every prompt | systemd's new profile script prints OSC 3008 "context" escape codes, which Guacamole's terminal shows as text | `dpkg-divert` the script on workstations |
| Second "Connect" showed "No recent connections" | Guacamole reused the browser's existing session and ignored the new signed login, whose connection list had expired | The portal signs out the old Guacamole session before each connect |
| 502 from the VPS after turning on upstream certificate checks | nginx's `proxy_ssl_verify_depth` defaults to 1, too short for a Let's Encrypt chain | `proxy_ssl_verify_depth 2` |
| Admin sign-in made the browser ask for the demo password again | Behind HTTP Basic auth, a 401 from the app makes browsers discard the cached credentials | The app answers 403, never 401 (Basic auth was later replaced by a sign-in page) |
| Admin sign-in failed: "Missing Authority Key Identifier" | Python 3.13+ checks certificates strictly, and Samba's auto-generated LDAPS certificate lacks that extension | A Let's Encrypt certificate for dc01 (`dc01.lab.radicallydecent.com`) |
| First portal deletion left records behind | Clean-up matched MAC links by `lnk_source`, which `find` in ansible-core 2.20 no longer returns | Match links by name. (Workstations no longer have install records at all.) |
| A worker restart could kill a build halfway | Builds ran as child processes of the portal's worker, and a deployment restarts the worker | Each operation runs in its own transient systemd unit (`lab-op-<id>`) |
