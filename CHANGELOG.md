# Changelog

All notable changes to CHUB are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.3](https://github.com/chodeus/chub/compare/v1.0.2...v1.0.3) (2026-04-19)


### Bug Fixes

* **deps:** update all non-major dependencies ([#24](https://github.com/chodeus/chub/issues/24)) ([814677d](https://github.com/chodeus/chub/commit/814677d26fc8876806f0464926abfa8aee806bce))

## [1.0.2](https://github.com/chodeus/chub/compare/v1.0.1...v1.0.2) (2026-04-19)


### Bug Fixes

* **deps:** update all non-major dependencies ([#14](https://github.com/chodeus/chub/issues/14)) ([9834f14](https://github.com/chodeus/chub/commit/9834f1489f24168e37b75b65ef58067c1e5d062a))
* **deps:** update all non-major dependencies ([#22](https://github.com/chodeus/chub/issues/22)) ([e8e7538](https://github.com/chodeus/chub/commit/e8e753828234443a5c0bd139e691e654a8aa9818))

## [1.0.1](https://github.com/chodeus/chub/compare/v1.0.0...v1.0.1) (2026-04-19)


### Bug Fixes

* **repo-events:** update chodeus-ops path to .github/workflows/ ([a9ff280](https://github.com/chodeus/chub/commit/a9ff280f898bd89dc4976ae01b868d16342f1061))


### Documentation

* flag CHUB-era additions on each module in wiki draft ([7e0bab8](https://github.com/chodeus/chub/commit/7e0bab8db5a81cd7680d79cd06b3062d1bd21d90))

## [1.0.0] — 2026-04-18

First release of CHUB. Identity fork from [DAPS](https://github.com/Drazzilb08/daps). Clean break — no data migration from DAPS.

### Changed (breaking)

- Project rebranded from **DAPS** to **CHUB — Chodeus' Media Script Hub**.
- Docker image moved: `ghcr.io/chodeus/chub:latest` (was `ghcr.io/chodeus/daps`).
- Default container name: `chub` (was `daps`).
- Database file: `chub.db` (was `daps.db`) — fresh install required.
- Config class renamed `DapsConfig` → `ChubConfig`; base module class renamed `DapsModule` → `ChubModule`.
- Frontend `localStorage` keys renamed (users will re-authenticate):
  - `daps-auth-token` → `chub-auth-token`
  - `daps-ui-state` → `chub-ui-state`
  - `daps_recent_searches` → `chub_recent_searches`
  - `daps_poster_assets_filters` → `chub_poster_assets_filters`
  - `daps_media_search_filters` → `chub_media_search_filters`
- All log prefixes changed `[DAPS]` → `[CHUB]`; container boot banner rebuilt with the ANSI-Shadow CHUB wordmark.

### Added

- **Complete UI redesign** — RoomSketch-inspired dashboard, floating rounded content panel on a tinted background, deep-indigo sidebar with small-caps section dividers, 5-colour pastel badge palette for quick-start cards.
- **New logos** — `assets/chub-logo.png` (shield/filmstrip icon) and `assets/chub-banner.png` (wordmark). Favicons regenerated at 16/32/48/64/180/.ico/SVG.
- **Typography** — Manrope (display) + Inter (body) replace Roboto.
- **Indigo-led cool palette** — primary `#463fbc` light / `#8767f7` dark, sourced from the sl1ckbe3ts palette.
- **Theme tokens file** — `frontend/src/css/theme/tokens.css` (radii + font families), loaded before light/dark themes.
- **Pastel badge CSS** — `--badge-1..5-bg/fg` variables and `.badge-bubble--1..5` component classes.
- **Full doc rewrite** — `README.md`, `docs/architecture.md`, `docs/deployment.md`, `SECURITY.md`.
- **Wiki drafts** — 10 pages drafted under `wiki-drafts/` (Home, Installation, Configuration, Modules, API, UI-Guide, Webhooks, Troubleshooting, Credits, FAQ).

### Credits

Built on the original [DAPS](https://github.com/Drazzilb08/daps) project by **[Drazzilb08](https://github.com/Drazzilb08)** — thank you for the scripts and inspiration that made this fork possible.
