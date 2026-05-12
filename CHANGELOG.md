# Changelog

All notable changes to CHUB are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.15.1](https://github.com/chodeus/chub/compare/v1.15.0...v1.15.1) (2026-05-12)


### Bug Fixes

* **assets:** make Asset Search top-bar actually filter, fix card layout ([6a044ef](https://github.com/chodeus/chub/commit/6a044ef7e9cb9eb3181059f6152937a88b068ff8))

## [1.15.0](https://github.com/chodeus/chub/compare/v1.14.1...v1.15.0) (2026-05-12)


### Features

* **posters:** redesign Asset Search + GDrive pages, add style tracking ([3d50f0a](https://github.com/chodeus/chub/commit/3d50f0a510bb248eeb31b5b0c03b370919517c51))


### Bug Fixes

* **poster_renamerr:** tolerate missing full_config in _get_assets_files ([685ab35](https://github.com/chodeus/chub/commit/685ab35261ff00cd501f1ee2cbc78db1489499c9))

## [1.14.1](https://github.com/chodeus/chub/compare/v1.14.0...v1.14.1) (2026-05-12)


### Bug Fixes

* **upgradinatorr:** reduce log noise and surface grabs clearly ([150d572](https://github.com/chodeus/chub/commit/150d572dda872df4def2e8e554aaafd246ae5252))

## [1.14.0](https://github.com/chodeus/chub/compare/v1.13.1...v1.14.0) (2026-05-12)


### Features

* **border_replacerr:** move visual config to dedicated page ([59911cf](https://github.com/chodeus/chub/commit/59911cfbe0c474d7c31c7f5dc85c586e4f64a7ea))


### Bug Fixes

* **upgradinatorr:** treat empty episode_data as monitored for Lidarr albums ([78d658e](https://github.com/chodeus/chub/commit/78d658edbe483f84a4c9eb606edf4dc7dfad438d))


### Refactoring

* **settings:** merge Interface page into General settings ([48bcc88](https://github.com/chodeus/chub/commit/48bcc886c68caa88efb904b6dfc807ca29f766fc))

## [1.13.1](https://github.com/chodeus/chub/compare/v1.13.0...v1.13.1) (2026-05-12)


### Bug Fixes

* upgradinatorr Lidarr and reporting flows ([9d1b338](https://github.com/chodeus/chub/commit/9d1b3382d18f504bd0ae8bf635ec0035d75f8a06))

## [1.13.0](https://github.com/chodeus/chub/compare/v1.12.0...v1.13.0) (2026-05-12)


### Features

* **border_replacerr:** themed image borders per holiday ([ffcb652](https://github.com/chodeus/chub/commit/ffcb6527e57e454a33829d6411a5bb9c1cb72734))


### Bug Fixes

* **settings:** consolidate general settings ([4e6ce3c](https://github.com/chodeus/chub/commit/4e6ce3cfe62006ffd553b6a9397fe75bb4bfe905))


### Documentation

* add AI disclaimer to README ([a07ae22](https://github.com/chodeus/chub/commit/a07ae22b7d17c2a8538b2ca502fd1bcea7aff010))

## [1.12.0](https://github.com/chodeus/chub/compare/v1.11.0...v1.12.0) (2026-05-12)


### Features

* **webhooks:** expose poster/add URL builder, drop UI duplicates ([7cc8070](https://github.com/chodeus/chub/commit/7cc80707f12c58379d545b72f9d86878c1c6f092))

## [1.11.0](https://github.com/chodeus/chub/compare/v1.10.2...v1.11.0) (2026-05-11)


### Features

* **poster_cleanarr:** mobile layout, transcoder cache stat, list fit ([ad1155c](https://github.com/chodeus/chub/commit/ad1155c2c5646b7bf6e133338b45522461b5dd0a))

## [1.10.2](https://github.com/chodeus/chub/compare/v1.10.1...v1.10.2) (2026-05-11)


### Bug Fixes

* **connector:** match Lidarr artists to Plex by MusicBrainz ID ([ff74d01](https://github.com/chodeus/chub/commit/ff74d017f741e5bf7e11f88a3300c096ee556a1f))

## [1.10.1](https://github.com/chodeus/chub/compare/v1.10.0...v1.10.1) (2026-05-11)


### Bug Fixes

* harden nestarr scanning and cache ([e43dccd](https://github.com/chodeus/chub/commit/e43dccdd52bc7b72014fb0a0ef3a8f3f09a73241))
* **health_checkarr:** scope to selected instances and propagate failures ([afd070e](https://github.com/chodeus/chub/commit/afd070e21de151036b4822175a977bb0e3832959))

## [1.10.0](https://github.com/chodeus/chub/compare/v1.9.3...v1.10.0) (2026-05-11)


### Features

* **poster_cleanarr:** expand in-use query and add overlays-only filter ([a646595](https://github.com/chodeus/chub/commit/a6465951bcc436ac02174f7cc2fda25a54506356))
* **upgradinatorr:** add count_mode for season/album-level search budgets ([64ce71f](https://github.com/chodeus/chub/commit/64ce71fbea3cebd420398366eaee418224eb4cd3))


### Bug Fixes

* **frontend:** drop superfluous arg from canRemoveDirectory call sites ([d0b00b5](https://github.com/chodeus/chub/commit/d0b00b597aa547c4abfcaba25825e9dabe26641b))


### Documentation

* **changelog:** polish v1.4.0 poster-cleanarr entry wording ([eb46f81](https://github.com/chodeus/chub/commit/eb46f81bc9a526025d506d49ac448d2b0732c28a))

## [1.9.3](https://github.com/chodeus/chub/compare/v1.9.2...v1.9.3) (2026-05-11)


### Bug Fixes

* **jduparr:** harden duplicate linking workflow ([9a7f6bc](https://github.com/chodeus/chub/commit/9a7f6bc827f67ee7ad463d850d218e45b14d33eb))

## [1.9.2](https://github.com/chodeus/chub/compare/v1.9.1...v1.9.2) (2026-05-10)


### Bug Fixes

* **deps:** update all non-major dependencies ([#91](https://github.com/chodeus/chub/issues/91)) ([4dd6c5c](https://github.com/chodeus/chub/commit/4dd6c5c9be15554a178e5ab2c16453e714d60852))
* **upgradinatorr:** satisfy backend lint ([20ceada](https://github.com/chodeus/chub/commit/20ceada2a09c4161fc09ca2a418bfafe5f7b1bc4))

## [1.9.1](https://github.com/chodeus/chub/compare/v1.9.0...v1.9.1) (2026-05-06)


### Bug Fixes

* **deps:** update all non-major dependencies ([#80](https://github.com/chodeus/chub/issues/80)) ([0ed1409](https://github.com/chodeus/chub/commit/0ed1409ae70b4cd077f7a5a16f29e86df274b94d))

## [1.9.0](https://github.com/chodeus/chub/compare/v1.8.0...v1.9.0) (2026-04-29)


### Features

* **border-replacerr:** surface preset holidays in preview dropdown ([585cf54](https://github.com/chodeus/chub/commit/585cf54b463f0f13345540fa4e4f168643a0dbe9))


### Bug Fixes

* **border-replacerr:** address CodeQL path-injection + empty-except findings ([87fbd71](https://github.com/chodeus/chub/commit/87fbd718b2075ed29d24ca83a83abfddd04d21b5))
* **border-replacerr:** img auth via ?token= query param + correct LoadingButton API ([8bdf0c8](https://github.com/chodeus/chub/commit/8bdf0c818a15db6640a5610d2c7d77eb0806689c))
* **border-replacerr:** use shared app.state.db instead of constructing ChubDB without logger ([97447b2](https://github.com/chodeus/chub/commit/97447b2c3fbe23d57aea6603c769dc889bd0609f))

## [1.8.0](https://github.com/chodeus/chub/compare/v1.7.0...v1.8.0) (2026-04-29)


### Features

* **border-replacerr:** live preview gallery page with holiday dropdown ([c299ec1](https://github.com/chodeus/chub/commit/c299ec1a4a5e57a439e5775815cd6a61966fdf35))


### Bug Fixes

* **border-replacerr:** drop unused os import (ruff F401) ([4ad1a67](https://github.com/chodeus/chub/commit/4ad1a67d0bef010ec0cc314c0e46300701ce14e4))


### Refactoring

* **settings:** regroup poster + border modules; drop dead toggle; library type from Plex ([ed19db2](https://github.com/chodeus/chub/commit/ed19db28f444648672dd46c8f1e808fc0598deed))

## [1.7.0](https://github.com/chodeus/chub/compare/v1.6.0...v1.7.0) (2026-04-28)


### Features

* **instances:** expose webhook_force_reupload toggle in UI ([35f1a87](https://github.com/chodeus/chub/commit/35f1a8750b1ad30a77fd1cbceff51528700d36b3))
* **settings:** expose webhook retry knobs in General settings ([17e6a4f](https://github.com/chodeus/chub/commit/17e6a4f7f3d5ce944d1b8525979fb34de5acf811))
* **settings:** expose webhook_secret in General settings ([1aeff9c](https://github.com/chodeus/chub/commit/1aeff9cbdf396874779e31460b81d666c489f0f4))
* **webhooks:** bump retry defaults and add per-instance force-reupload ([7a8d1fc](https://github.com/chodeus/chub/commit/7a8d1fceac19860f86aec72ec063bad119274b84))
* **webhooks:** event-type allow-list and season-aware path extraction ([9d43509](https://github.com/chodeus/chub/commit/9d435093ad88d2e41938e6259da1c7d9a928bb50))
* **webhooks:** persist dedup cache in webhook_cache table ([6b0b620](https://github.com/chodeus/chub/commit/6b0b620dd4327a96aded642ad7229048adfbf389))


### Bug Fixes

* **deps:** update all non-major dependencies ([#65](https://github.com/chodeus/chub/issues/65)) ([3bca7d3](https://github.com/chodeus/chub/commit/3bca7d313fdac85e6586fe39541b70f02bbdd057))
* **webhooks:** drop eventType from dedup hash ([3f8a599](https://github.com/chodeus/chub/commit/3f8a59911979af14a4c0259e2e55afd5c8346a22))


### Documentation

* refresh webhook section for new dedup/event model ([c4571e1](https://github.com/chodeus/chub/commit/c4571e1353b237778ca9b15acae0611cfbcded12))

## [1.6.0](https://github.com/chodeus/chub/compare/v1.5.0...v1.6.0) (2026-04-24)


### Features

* **notifications:** add border_replacerr and sync_gdrive surfaces ([553980a](https://github.com/chodeus/chub/commit/553980a8dc320215216a796b67be4cd6d618819e))


### Bug Fixes

* **media-api:** strip /config disk prefix from Lidarr artist poster paths ([2485aab](https://github.com/chodeus/chub/commit/2485aab6be80cfa8796723bd5c37e3a8bd51a6e2))
* **media-search:** include JWT in poster &lt;img src&gt; query param ([c8ea139](https://github.com/chodeus/chub/commit/c8ea1398186cc25abd0ada426d533615f778e1cc))

## [1.5.0](https://github.com/chodeus/chub/compare/v1.4.1...v1.5.0) (2026-04-24)


### Features

* **media-api:** proxy poster image endpoint ([c5b8707](https://github.com/chodeus/chub/commit/c5b8707f4ec1f47d4a6fb0442f2f6181ecd26fa4))
* **media-search:** vertical row layout with posters ([afa037c](https://github.com/chodeus/chub/commit/afa037c26dfd6b76308223da7481eb5c93c78e51))


### Bug Fixes

* **auth:** constant-time compare, drop username from fail logs ([31a5230](https://github.com/chodeus/chub/commit/31a5230f412797dafba66432802e58a828e8a510))
* **scheduler,job-processor:** off-thread health snapshot, plug ARR session leak ([aa422c5](https://github.com/chodeus/chub/commit/aa422c5637349145c6b8b0d044096be747f427b2))
* **security:** SSRF guard on Plex, harden poster upload ([db2f657](https://github.com/chodeus/chub/commit/db2f657c7c590c1bd4708a724bc082e6d0b8c584))
* **webhooks,arr:** rate-limit endpoints and honor ARR Retry-After ([226ed26](https://github.com/chodeus/chub/commit/226ed2628a2d1838a1435dab1ad4a1440461f8fe))


### Refactoring

* **db:** allowlist table names in DBWorker ([9ce203e](https://github.com/chodeus/chub/commit/9ce203e7085e58e7844e69c17da6dbc5f262744e))
* **frontend:** drop innerHTML for React state, remove dead code ([16d64cc](https://github.com/chodeus/chub/commit/16d64ccd80545b4c03eb8ee2a47502f171242dcc))


### Documentation

* refresh README, architecture, add dashboard screenshots ([4ab0c3e](https://github.com/chodeus/chub/commit/4ab0c3eb71bc43a8e01307598d901506ba71f660))

## [1.4.1](https://github.com/chodeus/chub/compare/v1.4.0...v1.4.1) (2026-04-23)


### Bug Fixes

* **media-api:** incomplete-metadata ignores fields ARRs never populate ([1269bbf](https://github.com/chodeus/chub/commit/1269bbf73919d7947bbf4fb182a93ffbc7d3d46e))
* **media-api:** orphaned detection used raw "id" key after normalize ([0fd8a47](https://github.com/chodeus/chub/commit/0fd8a47ddd02b0bbfad12b5aa239414b00f4e1c4))


### Performance

* **poster-cleanarr:** prune deleted variants locally instead of full rescan ([9695776](https://github.com/chodeus/chub/commit/969577606a0960abf3d2c9d4c807cbdd95080331))

## [1.4.0](https://github.com/chodeus/chub/compare/v1.3.3...v1.4.0) (2026-04-23)


### Features

* **media-manage:** show folder paths on duplicate rows + live detail in Resolve modal ([d66d68c](https://github.com/chodeus/chub/commit/d66d68c1dfed71e2794745b3e8999c6a74d2af38))


### Bug Fixes

* **media-api:** route Library Maintenance endpoints before /{media_id} + remove path-replace + import ([e6074e0](https://github.com/chodeus/chub/commit/e6074e071c15bf53235fc3d6bb7fa828149d67fe))

## [1.3.3](https://github.com/chodeus/chub/compare/v1.3.2...v1.3.3) (2026-04-23)


### Bug Fixes

* **media-stats:** give tab labels room to breathe from their counts ([3cd0840](https://github.com/chodeus/chub/commit/3cd0840b2b13aade9f7a9ce1f35e5f3ece9ab4d3))
* **nestarr:** remove cosmetic dry_run + unify scheduled and UI scan cache ([6ad75c6](https://github.com/chodeus/chub/commit/6ad75c60cea1103bd31ed8cf7a99b13487b2ec8d))

## [1.3.2](https://github.com/chodeus/chub/compare/v1.3.1...v1.3.2) (2026-04-23)


### Bug Fixes

* **fields:** stop API-token fields from triggering password-manager prompts ([e5a244b](https://github.com/chodeus/chub/commit/e5a244b8c38ffeee42f1f068bebe0fc38cdb2901))
* **login:** prevent iOS zoom-on-focus by raising input font-size to 1rem ([d4d1299](https://github.com/chodeus/chub/commit/d4d129983df4724cc94829c0adfc714f2c323b16))
* **styles:** add missing utility CSS variants + replace dead Tailwind-arbitrary classes ([84d82bb](https://github.com/chodeus/chub/commit/84d82bb69f83598486744f4960a34e4c57daac39))


### Refactoring

* **media-stats:** replace stacked breakdowns with tabbed bar charts ([dd0a47d](https://github.com/chodeus/chub/commit/dd0a47dc1b37bd5e62dcc5b2d15a36ea5f0a3088))


### Documentation

* **plex-metadata:** explain best-effort except-pass in _load_library_sections ([fc7b028](https://github.com/chodeus/chub/commit/fc7b02889367da6dfe0bef891a676b1e1c3dfa10))

## [1.3.1](https://github.com/chodeus/chub/compare/v1.3.0...v1.3.1) (2026-04-21)


### Bug Fixes

* **fields:** drop htmlFor from composite-field wrappers ([9963ce7](https://github.com/chodeus/chub/commit/9963ce7c3f1ae7636b7b9ff49a914107b4945d9c))
* **plex-metadata:** dedupe bundles by rating_key ([db63cef](https://github.com/chodeus/chub/commit/db63cefc206720a3ebcc4676c0516b7b82377201))
* **poster-cleanarr:** collapse Refresh scan + Run scan into one button ([cf88f08](https://github.com/chodeus/chub/commit/cf88f08bf768af6203bcd6b5cf26e550e1101477))
* **poster-cleanarr:** key bundle rows by bundle_path, not rating_key ([b3db902](https://github.com/chodeus/chub/commit/b3db9023c955817e8f8b641f90e89d9cfde78f0a))
* **settings:** exclude runtime-only Pydantic fields from Modules page ([7441770](https://github.com/chodeus/chub/commit/7441770a15f4ce82f1739d6c49c131ae6de99ec0))

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

* **poster-cleanarr:** add library, media type, and variant kind filters ([1a61124](https://github.com/chodeus/chub/commit/1a61124ea4e335c8964df97514f0cc23020ac3ee))
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
