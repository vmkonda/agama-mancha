# Deploying Agama Mancha to a VPS (GitHub Actions)

Agama Mancha runs on a Linux VPS behind the web server that's already there (Caddy or nginx), on a
subdomain of its own. **Pushing to the `deploy` branch updates it**: GitHub Actions runs the tests,
then connects to the VPS over SSH and runs `scripts/linux/deploy.sh`, which pulls that commit,
updates the dependencies and restarts the service. Nothing else on the VPS is touched.

```
git push origin main:deploy              # release what's on main
git push -f origin <commit>:deploy       # roll back to an earlier commit
```

What runs where:

| On the VPS | On members' machines (the Mac Studio for now) |
|---|---|
| the app (`amocr serve --hosted`), members only, on 127.0.0.1:8770 | Surya and Tesseract (`amocr worker`) |
| HTTPS, by the existing Caddy or nginx | the local AI (`amocr fix-worker`, Ollama with qwen) |
| Ollama with `bge-m3`, for the library's search (CPU is fine) | each member's Claude (the chat and study listeners) |
| `amocr sync` with Proton Drive every 30 minutes | |

Members' machines only connect **out** to the VPS over HTTPS; the VPS never connects to them.

**Size:** about 1 GB of RAM for the app, 2–3 GB more for Ollama with `bge-m3`; a few GB of disk
for `data/` (one book with its scans is about 200 MB) plus the Python environment.

## 1. On the VPS, once

As root (or with sudo), a user of its own, so this app can't touch Bindu or the website:

```sh
sudo adduser --disabled-password --gecos "" agama
sudo loginctl enable-linger agama            # its services run without anyone logged in
```

Then as that user (`sudo -iu agama`):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh          # uv, into ~/.local/bin
git clone https://github.com/vmkonda/agama-mancha.git ~/agama-mancha
cd ~/agama-mancha && uv sync --extra librarian
```

**Ollama** (as root): `curl -fsSL https://ollama.com/install.sh | sh`, then `ollama pull bge-m3`.
It listens on 127.0.0.1:11434, which the service file already points to.

**The data.** Copy the Windows server's `data\` folder (library, search index, books, members,
proofreading) to `~/agama-mancha/data/`, once, while the Windows server is stopped so nothing
changes during the copy, e.g. from the Windows machine:

```powershell
scp -r data agama@<vps>:agama-mancha/
```

`data/hosted/` holds the members, password hashes, sessions and tokens: it goes from machine to
machine directly, never through Proton or GitHub.

**Proton Drive, for `amocr sync`** (as `agama`): `uv run amocr setup-proton`, then sign in with
the Proton tool's `auth login` in a browser (the person who owns the Proton account does this; the
password is never shared), then:

```sh
uv run amocr init --operator "Agama Mancha server" --proton-root "/shared-with-me/<team folder>" --material "/shared-with-me/[OCR Mirror]/Agama Mancha"
uv run amocr doctor          # the Proton lines should say ok
```

**The services** (as `agama`):

```sh
mkdir -p ~/.config/systemd/user
cp scripts/linux/agama-mancha.service scripts/linux/agama-mancha-sync.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agama-mancha agama-mancha-sync.timer
curl -s http://127.0.0.1:8770/api/version      # {"code": "<commit>"}
```

The service files assume the checkout is at `~/agama-mancha`; edit `WorkingDirectory` if not.

**HTTPS.** Add a site to the existing web server: `scripts/linux/Caddyfile.example` or
`scripts/linux/nginx.conf.example`, with the subdomain (e.g. `agama.<your domain>`) and a DNS
record pointing to the VPS. Two settings matter: the proxy must pass `X-Forwarded-Proto` (so the
sign-in cookie is marked Secure), and allow requests to stay open for 2 minutes (listeners and
workers wait up to 55 s for work). Then open `https://agama.<your domain>`: the sign-in page.

## 2. The deploy key

On your own machine, a key used for nothing else:

```sh
ssh-keygen -t ed25519 -f agama-deploy -N "" -C "github-actions deploy"
```

On the VPS, in `~agama/.ssh/authorized_keys`, add the public key **restricted to the deploy
script**, so this key can do nothing else, whatever it's asked:

```
command="/home/agama/agama-mancha/scripts/linux/deploy.sh",restrict ssh-ed25519 AAAA… github-actions deploy
```

Note the VPS's host key for pinning: `ssh-keyscan -p <port> <vps host>` (from a machine you trust,
and check the fingerprint against `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the VPS).

## 3. GitHub

In the repository: **Settings → Environments → New environment → `production`**, then add these
**environment secrets**:

| Secret | Value |
|---|---|
| `VPS_HOST` | the VPS's host name or IP |
| `VPS_USER` | `agama` |
| `VPS_PORT` | the SSH port, if not 22 |
| `VPS_SSH_KEY` | the **private** key (`agama-deploy`, the whole file) |
| `VPS_KNOWN_HOSTS` | the `ssh-keyscan` output |

Optionally, under the environment, **Required reviewers** (a deploy then waits for a click) and
**Deployment branches → `deploy` only**. Then delete the private key from your machine: GitHub has
the only copy it needs.

Create the branch once: `git push origin main:deploy`. The **deploy** workflow (Actions tab) runs
the tests, then the deploy; its log ends with `running <commit> (was <commit>)`. If the server
doesn't answer with the new commit within two minutes, the job fails and shows the service's last
log lines; the previous code isn't restored automatically: push the last good commit to `deploy`.

## 4. Switching the team over

1. Stop the Windows server and remove its scheduled tasks
   (`Unregister-ScheduledTask -TaskName "Agama Mancha redeploy","Agama Mancha sync" -Confirm:$false`),
   so only the VPS writes to Proton from then on.
2. Copy `data\` to the VPS (above), start the service, check it.
3. On each member's machine, set `AGAMA_SERVER=https://agama.<your domain>` in
   `~/.config/agama-mancha/hosted.env` (the token stays the same: it's in `data/hosted/`), then
   `uv run librarian hosted check`.
4. Restart the Mac's workers and listeners (`amocr worker`, `amocr fix-worker`, the chat listeners)
   so they use the new address.

## Day to day

| | |
|---|---|
| release | `git push origin main:deploy` (or Actions → deploy → Run workflow) |
| roll back | `git push -f origin <commit>:deploy` |
| logs | `journalctl --user -u agama-mancha -f`; sync: `journalctl --user -u agama-mancha-sync`, `data/sync.log` |
| restart by hand | `systemctl --user restart agama-mancha` |
| members | `uv run amocr member add "Name" --role proofreader` (prints an invite link) |
| backups | `data/hosted/` (members) privately, e.g. nightly to another machine; the books are on Proton through sync |

A change that needs more than a restart (a new index format, say) says so in its pull request.
