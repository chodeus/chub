# Changelog

All notable changes to CHUB are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.3.0](https://github.com/chodeus/chub/compare/v1.2.0...v1.3.0) (2026-04-20)


### Features

* **plex-metadata:** surface Plex-sourced variants as read-only ([5adeadc](https://github.com/chodeus/chub/commit/5adeadc0d5c6f3b9417ec3768b1564061e0765d7))
* **poster-cleanarr:** persist scan state and sort bundles alphabetically ([daf1ddd](https://github.com/chodeus/chub/commit/daf1ddd3ddb9d6784dd8175375771ce0ba91800f))
* **poster-cleanarr:** rewrite page as master-detail with TV drill-down ([8f841d6](https://github.com/chodeus/chub/commit/8f841d681ebf5e41ff0d5f66c3f99317e494a562))


### Bug Fixes

* **docker:** include .release-please-manifest.json in build context ([88cbcb8](https://github.com/chodeus/chub/commit/88cbcb80dbfbbb4db2d458fab3bdae43a02b39c1))
* **plex-maintenance:** wire the new module into every surface it needs ([dd211af](https://github.com/chodeus/chub/commit/dd211af4b50507d71918bbde84b3334a8cc95a9d))
* **poster-cleanarr:** poster-shaped tiles, flush borders, new sort order ([3159e64](https://github.com/chodeus/chub/commit/3159e64cecf469438e1b7a9c86ec4d236c58e229))
* **poster-cleanarr:** restore master-detail layout, full mode coverage, music skip ([e4fcda8](https://github.com/chodeus/chub/commit/e4fcda8b354217ca2265a07d073891cbaa1457da))
* **poster-cleanarr:** stop auto-scanning, log UI actions, quieter INFO, wider pane ([227b40f](https://github.com/chodeus/chub/commit/227b40f32adddc9fd7ac0a66bba33c2c992e6983))


### Refactoring

* **plex-maintenance:** extract Plex server tasks into its own module ([0da6a1e](https://github.com/chodeus/chub/commit/0da6a1e504c4e5239ecfa746a926a7b883ff26a3))

## [1.2.0](https://github.com/chodeus/chub/compare/v1.1.1...v1.2.0) (2026-04-20)


### Features

* **media-stats:** render skewed breakdowns as horizontal bars ([f6627e2](https://github.com/chodeus/chub/commit/f6627e2a23eed3c8d1ff867e600b08d55234a0a6))


### Bug Fixes

* **poster-cleanarr:** auto-select the lone Plex instance ([c48ecae](https://github.com/chodeus/chub/commit/c48ecaea947e76d4f081e7e05be0578d1a93a9ed))
* **poster-cleanarr:** fire scan on first Refresh click ([43a5a78](https://github.com/chodeus/chub/commit/43a5a78f5240d656b1419df593ae188e7a0ea2b7))
* **poster-preview:** accept absolute path without location as a root ([99d11b7](https://github.com/chodeus/chub/commit/99d11b7d44a3343451e28b0fc4c14e067ea7c296))
* **release:** bump VERSION to 1.1.1 to match release-please manifest ([1d8f0f2](https://github.com/chodeus/chub/commit/1d8f0f2c93328efd4b7f16e498a7265c9e2ed747))


### Refactoring

* **release:** derive VERSION from release-please manifest ([15e5f04](https://github.com/chodeus/chub/commit/15e5f04af38c3fae82bbaf5e33869a653dcc4931))

## [1.1.1](https://github.com/chodeus/chub/compare/v1.1.0...v1.1.1) (2026-04-20)


### Bug Fixes

* **jobs:** fit table and filter chips on mobile viewport ([7055902](https://github.com/chodeus/chub/commit/7055902a15858e91f14e14c94d248e1fb031f8c8))
* **poster-cleanarr:** don't show "no variants" while scan is still loading ([8ccadcc](https://github.com/chodeus/chub/commit/8ccadccd8f3dd150c6dd03a98dc023d867831a97))
* **poster:** make asset tile titles readable ([dbbe7a6](https://github.com/chodeus/chub/commit/dbbe7a6cc97922b0f36ea7ee6298d75be0933ba5))
* **release:** bump VERSION to 1.1.0 to match manifest; harden release-please config ([755fad3](https://github.com/chodeus/chub/commit/755fad37318d44e7c79c1cec653782e734baa5dd))
* **ui:** stop mobile drawer hiding Dashboard entry behind header ([26f5e35](https://github.com/chodeus/chub/commit/26f5e356b6c28c55e805e634ff3b15f22bdc13c3))

## [1.1.0](https://github.com/chodeus/chub/compare/v1.0.4...v1.1.0) (2026-04-20)


### Features

* **poster-cleanarr:** ImageMaid-style filters — library, media type, variant kind ([1a61124](https://github.com/chodeus/chub/commit/1a61124ea4e335c8964df97514f0cc23020ac3ee))
* **poster-cleanarr:** rename route/file to match label, add per-file audit logs ([e495ade](https://github.com/chodeus/chub/commit/e495adeaf40922de713d6322f092dfa9da1d2009))
* **ui:** clear the deferred audit list — health cards, recent queries, standardized headers ([26c28a7](https://github.com/chodeus/chub/commit/26c28a728776e7541db816fc9bc136a3521aac06))
* **ui:** per-route browser tab titles ([4b8594d](https://github.com/chodeus/chub/commit/4b8594d9270522baab908115dc5818dbceccfa75))
* **ui:** polish pass — last-failure card, run-now confirm, orphan/cache health, breadcrumb cleanup, cleanarr filter dedup, version drift guard ([6ae9165](https://github.com/chodeus/chub/commit/6ae9165f2bb9200ff592d1fa487efd64bf8066b3))


### Bug Fixes

* **frontend:** dashboard rework, schema guard, poster lightbox, bug fixes ([23b3e5c](https://github.com/chodeus/chub/commit/23b3e5c126bcb94c3de7dcfecb402d3bfebc0ddc))
* poster cleanarr 500 — move plex-db working dir to /config; surface error in UI ([bd36f8c](https://github.com/chodeus/chub/commit/bd36f8cc00b6f14f0d59499c7b1639235bddeb67))
* **poster-cleanarr:** scope orphan cleanup to configured asset roots ([3962f54](https://github.com/chodeus/chub/commit/3962f54b15237971c7436639e55994b12fdb08d1))
* **ui:** ctrl+r hijack, version sync, dashboard rework, cleanarr auto-scan, modules ordering ([37e0340](https://github.com/chodeus/chub/commit/37e034025daf97fe455d3716d9beb683863ae88d))
* **ui:** production-readiness sweep — jobs duration, lightbox, instances card, disk dedup, breadcrumbs, version display ([07cd0bc](https://github.com/chodeus/chub/commit/07cd0bcafb67dfa92d3ca309e8cd29fd99f420f9))
* **webui:** resolve audit findings from full walk-through ([227a5cc](https://github.com/chodeus/chub/commit/227a5ccff661e45997b023eadded9f37c3adf838))


### Documentation

* **readme:** drop :ro from Kometa mount; trim security step ([dddff68](https://github.com/chodeus/chub/commit/dddff686146de7fe78bb0ce2a47c05a0772d55bc))
* **readme:** rewrite for end-user focus ([fc172bd](https://github.com/chodeus/chub/commit/fc172bd5b3d3e4e50d9eecaffddec2e41129e245))
* **wiki:** rewrite wiki drafts to match actual code ([d2ae40c](https://github.com/chodeus/chub/commit/d2ae40ce27a45223a7b4ed700a6d518f36864827))

## [1.0.4](https://github.com/chodeus/chub/compare/v1.0.3...v1.0.4) (2026-04-19)


### Bug Fixes

* **deps:** update all non-major dependencies ([#27](https://github.com/chodeus/chub/issues/27)) ([ec0b524](https://github.com/chodeus/chub/commit/ec0b524da4868695e6a57cf37b1d3efa58ca844e))

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
