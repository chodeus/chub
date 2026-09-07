# Security Policy

## Scope

CHUB is a **self-hosted, single-user application** intended to run on a private network (behind a reverse proxy, VPN, or both). The threat model assumes a trusted local network; CHUB is not hardened for unauthenticated public-internet exposure.

## Supported versions

Only the latest release of CHUB is supported. Because CHUB uses rolling releases against `main`, security fixes land on the latest image tag (`ghcr.io/chodeus/chub:latest`) and the next tagged release.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Preferred channels, in order:

1. **GitHub Security Advisories** — use private [vulnerability reporting](https://github.com/chodeus/chub/security/advisories/new) on the `chodeus/chub` repo.
2. **Direct contact** — reach the maintainer via their GitHub profile.

### What to include

- Description of the vulnerability and its potential impact
- Steps to reproduce
- Affected version or commit
- Suggested fix or mitigation (optional)

### Response timeline

| Stage | Target |
|---|---|
| Acknowledgement | within 48 hours |
| Initial assessment | within 1 week |
| Fix / mitigation | severity-dependent — see below |

### Severity classification

| Severity | Description | Target fix time |
|---|---|---|
| Critical | RCE, authentication bypass, data exfiltration | 48 hours |
| High | Privilege escalation, injection, path traversal | 1 week |
| Medium | Information disclosure, DoS | 2 weeks |
| Low | Minor issues, hardening improvements | next release |

---

## Security posture

### What CHUB does

- **Authentication** — username + password with bcrypt hashing. Session tokens are JWTs stored client-side in `localStorage['chub-auth-token']`.
- **Login rate limiting** — token-bucket limiter (`backend/util/rate_limiter.py`) applied to `POST /api/auth/login`: 1 req / 5 s with a burst of 5. Defense against credential-stuffing on a local-network deploy.
- **SSRF guard** — `backend/util/ssrf_guard.py` blocks outbound requests to cloud-metadata endpoints (`169.254.169.254`, `metadata.google.internal`), reserved/link-local/multicast ranges, and non-`http(s)` schemes. Applied to instance-health probes and scheduler snapshots.
- **Path validation** — `backend/util/path_safety.py` rejects null bytes and values starting with `-` on path-valued config (`jduparr.hash_database`, `sync_gdrive.sync_location`, `sync_gdrive.gdrive_sa_location`, GDrive folder IDs) to prevent arg-smuggling in list-form `subprocess` calls.
- **Log redaction** — `SmartRedactionFilter` in `backend/util/logger.py` scrubs JWTs, Bearer tokens, bcrypt hashes, Radarr/Sonarr `X-Api-Key`, `X-Plex-Token`, JWT/webhook secrets, Discord webhook URLs, Google OAuth client IDs/secrets, AWS access keys, and GitHub tokens before they hit disk.
- **Webhook auth (optional)** — if `general.webhook_secret` is set in config, webhook endpoints require either `X-Webhook-Secret` header or `?secret=` query param (HMAC-compared). If unset, webhooks accept unauthenticated traffic (matches Sonarr/Radarr's default posture).
- **Container hardening** — image runs as a non-root user (`dockeruser`, PUID/PGID configurable). Compose file sets `no-new-privileges:true` and mounts `/tmp` as tmpfs.
- **Dependency posture** — `dependency-auditor` and `security-auditor` skills are available for pre-release audit passes; Dependabot monitors pip + npm + Actions; CodeQL runs on push and weekly.

### What CHUB does not do

- **TLS termination** — CHUB serves plain HTTP. Put it behind a reverse proxy (Caddy, Nginx, Traefik) for HTTPS.
- **Public-internet exposure** — there is no WAF, IP allowlist, or DDoS mitigation. Don't put CHUB on the public internet without a proxy that provides these.
- **API key auth for `/api/*`** — authenticated endpoints use JWT from the browser session. For integrations, generate a long-lived token via the login endpoint; there is no separate API-key system.
- **Secrets-at-rest encryption** — `config.yml` contains plaintext API keys (Plex, Radarr, Sonarr, Lidarr, Google Drive OAuth). Protect it with filesystem permissions (`chmod 600`) and back up the config directory to an encrypted store.

---

## Deployment recommendations

1. **Never expose CHUB directly to the internet** without a reverse proxy and TLS.
2. **Restrict `config.yml`** to `0600` or stricter; it holds every external API credential.
3. **Use per-service API tokens** with least-privilege scopes where your ARR stack supports it.
4. **Keep the image current** — `docker compose pull && docker compose up -d` pulls the latest fixes.
5. **Watch CodeQL + Dependabot alerts** on the repo's Security tab.
6. **Rotate the webhook secret** if you publish webhook URLs externally (e.g. Tautulli relay).
7. **Back up `chub.db` + `config.yml`** regularly — see [Deployment → Backup](docs/deployment.md#backup--restore).

---

## Credits

CHUB builds on the original [DAPS](https://github.com/Drazzilb08/daps) project by **Drazzilb08**. Security improvements in CHUB (rate limiting, SSRF guard, path-safety validation, log redaction expansion) were added in a dedicated audit pass on top of the DAPS foundation.
