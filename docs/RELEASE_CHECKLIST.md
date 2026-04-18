# Release checklist — CHUB repo flip

Manual steps to cut the brand-new `chodeus/chub` repo from the current `chodeus/daps` experimental branch. These are **not** code — they're one-shot operational steps the maintainer runs when ready.

Run these in order. Each step is a single unit; don't start the next until the previous is confirmed done.

---

## Pre-flight

- [ ] All rebrand + restyle work committed on `experimental` (`chodeus/daps`)
- [ ] `npm run build` passes clean
- [ ] Manual smoke test: docker build + docker compose up + open UI in a browser, confirm indigo theme + banner + dashboard render correctly in light and dark
- [ ] `grep -rn -iE 'daps' backend/ frontend/src/ main.py` returns zero hits (intentional `Drazzilb08/daps-gdrive-presets` + credit-line refs excepted)
- [ ] Wiki drafts in `wiki-drafts/` reviewed end-to-end
- [ ] CHANGELOG entry reads correctly

## Create the new repo

- [ ] Go to https://github.com/new and create **`chodeus/chub`** — Private initially, empty, no auto-init README/license/gitignore
- [ ] Write description: `CHUB — Chodeus' Media Script Hub. Self-hosted media asset manager for your Plex/ARR stack.`
- [ ] Set topics: `plex`, `radarr`, `sonarr`, `lidarr`, `media-management`, `docker`, `self-hosted`, `poster-manager`
- [ ] Settings → Features: enable **Wiki**, enable **Discussions** (optional), enable **Issues**, disable Projects unless you use it

## Flip git history locally

Working directory: current CHUB clone (what is currently `chodeus/daps` experimental).

- [ ] Confirm you have no uncommitted work: `git status`
- [ ] **Create a safety branch** in the old repo before detaching: `git branch chub-preflip-backup` (keeps a local-only pointer to current HEAD in case you need to recover)
- [ ] Drop history: `rm -rf .git`
- [ ] Re-init: `git init -b main`
- [ ] Stage everything: `git add -A`
- [ ] Verify no unwanted files (secrets in `config/`, stray build outputs):
  - `git status | head -40`
  - Double-check `.gitignore` covers `config/config.yml`, `config/*.db`, `frontend/node_modules/`, `frontend/dist/`, `__pycache__/`, `.venv/`
- [ ] Initial commit:
  ```
  git commit -m "Initial commit — CHUB — Chodeus' Media Script Hub"
  ```
- [ ] Wire remote: `git remote add origin git@github.com:chodeus/chub.git`
- [ ] Push: `git push -u origin main`
- [ ] Browse the new repo on GitHub, confirm file tree looks right

## Repo configuration

- [ ] Add LICENSE if not already present (MIT, copyright `chodeus` and `Drazzilb08`)
- [ ] Upload `assets/chub-social-preview.png` as the repo social preview (Settings → General → Social preview)
- [ ] Enable **Dependabot alerts** (Settings → Security)
- [ ] Enable **secret scanning** + **push protection**
- [ ] Enable **CodeQL** (Settings → Security → Code scanning)
- [ ] Add required CI secrets:
  - `GHCR_TOKEN` — GitHub personal access token with `write:packages`
  - Any Discord / notification webhook URLs your workflows use
  - Any other secrets referenced in `.github/workflows/*.yml`
- [ ] Add branch protection on `main`: require PRs, require status checks (once CI runs at least once)

## First CI run

- [ ] Trigger the release workflow manually (Actions → Release → Run workflow) OR push a tag to trigger it
- [ ] Confirm **`ghcr.io/chodeus/chub:latest`** builds and publishes successfully
- [ ] Pull the image locally and run it to confirm end-to-end: `docker run --rm -p 8000:8000 ghcr.io/chodeus/chub:latest`

## Assets & presentation

- [ ] Upload `assets/chub-logo.png` as the package avatar on ghcr.io (Settings → Package → Avatar)
- [ ] If you maintain a Docker Hub mirror: update avatar + description there too
- [ ] Pin the repo on your GitHub profile (Profile → Customize your pins)

## Wiki

- [ ] `git clone https://github.com/chodeus/chub.wiki.git` in a separate directory
- [ ] Copy every `wiki-drafts/*.md` into the wiki clone
- [ ] Copy `wiki-drafts/images/*` into `images/` in the wiki clone (create if missing)
- [ ] `git add -A && git commit -m "Initial wiki" && git push`
- [ ] Verify pages render correctly at `https://github.com/chodeus/chub/wiki`

## Flip public + decommission old repo

- [ ] Make `chodeus/chub` **public** (Settings → Danger zone → Change visibility)
- [ ] Post-public smoke: open the repo in an incognito window, confirm rendering
- [ ] On `chodeus/daps`: add a final commit to README pointing at the new repo:
  ```
  > # This project has moved to [chodeus/chub](https://github.com/chodeus/chub).
  ```
- [ ] **Archive** `chodeus/daps` (Settings → Danger zone → Archive this repository) — keeps old links working, blocks new issues/PRs. Alternative: delete it outright; up to you.

## External cleanup

- [ ] Update profile README / pinned repos / homelab links to point at `chodeus/chub`
- [ ] Delete orphaned `ghcr.io/chodeus/daps` image versions if you don't want them around
- [ ] Post an announcement — Discord server, Reddit thread, wherever DAPS discussion lives — so people know where it moved to
- [ ] If Drazzilb08 cares to know, give them a heads-up (the credit line is already in README / architecture / SECURITY / Credits wiki page)

---

## Rollback plan

If something goes sideways between the git reset and the push:

- The `chub-preflip-backup` branch in your local clone still points at the pre-flip commit
- You can `git reflog` to find HEAD before the `rm -rf .git`
- If `chodeus/daps` is still live on GitHub, you can `git remote add rescue git@github.com:chodeus/daps.git && git fetch rescue` to pull history back

If the new repo pushed bad content and you haven't gone public:

- Delete `chodeus/chub` from GitHub, recreate it, push again

Once the repo is public, you're committed. Plan accordingly.
