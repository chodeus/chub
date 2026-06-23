# Changelog

All notable changes to CHUB are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.34.0](https://github.com/chodeus/chub/compare/v2.33.0...v2.34.0) (2026-06-23)


### Features

* **api:** cached Plex library catalog endpoint ([5e8c00a](https://github.com/chodeus/chub/commit/5e8c00ae32e56d8013a35cbe0e17870db2584648))
* **config:** add PlexScope model + plex_scope split with legacy coercion ([655c95a](https://github.com/chodeus/chub/commit/655c95a187caff0b49661267dbfecd92e810e8c5))
* **config:** migrator splits module instances into instances + plex_scope ([8cf86e9](https://github.com/chodeus/chub/commit/8cf86e9650ccec7ad47f2becd6a747b9348a44b5))
* **connector:** consume plex_scope + match_collections for media/collections ([539cc1c](https://github.com/chodeus/chub/commit/539cc1c6d1e27be1c6e6a91cd4c7dc244bfbb8ff))
* **modules:** migrate poster/asset/upload consumers to plex_scope ([28ec94c](https://github.com/chodeus/chub/commit/28ec94ca70c667f3c65ffc017fe3a025749738ab))
* **ui:** explicit Libraries catalog section on Plex instance card ([a96c5e6](https://github.com/chodeus/chub/commit/a96c5e639564d7ddf89ca2a25ca068e050ef09d4))
* **ui:** plex_scope field (catalog picker + match_collections) ([642c305](https://github.com/chodeus/chub/commit/642c305e49a4ccc4545558aa3296e34adbf4153c))
* **ui:** split instances/plex_scope in poster/asset/unmatched schema ([fea06d5](https://github.com/chodeus/chub/commit/fea06d54a6cd86f2bcac2f765bbdbc77f5fbde53))
* **unmatched:** read plex_scope for instance/library filtering ([ca924c7](https://github.com/chodeus/chub/commit/ca924c715a2e7ae6c720ff053cebf444715251c8))


### Bug Fixes

* **api:** include plex_scope instances in module test endpoint ([0004eda](https://github.com/chodeus/chub/commit/0004eda71b734162108e7c34e41eeaf5ea2af5b7))
* **api:** SSRF-guard Plex library fetch (single + catalog endpoints) ([e2573ef](https://github.com/chodeus/chub/commit/e2573efc3c18569a68a11402c7f4a6aa5b5d364c))
* **config:** dedup/idempotency + ambiguous-name safety in plex_scope relocation ([71b8ff8](https://github.com/chodeus/chub/commit/71b8ff86d9d8e9d4ca942995bd268afffc4ff0fe))
* **config:** relocate bare Plex-name strings in instances into plex_scope ([d46cbc2](https://github.com/chodeus/chub/commit/d46cbc2689f5136e703663d468ea1ad38914ca87))
* **config:** stop migrator flattening supported unmatched_assets Plex scope ([06f33e0](https://github.com/chodeus/chub/commit/06f33e006bc0fa727c8c6ad16dc7da91b489db23))
* **css:** restore utilities and colour aliases dropped by the Tailwind migration ([f4b13e3](https://github.com/chodeus/chub/commit/f4b13e37a55540512313619eb2085587d5efcf1b))
* **ui:** preserve unrecognized instance strings on save in InstancesField ([381314e](https://github.com/chodeus/chub/commit/381314ef16e4cf67a86566429efdbf49c8124d2a))


### Refactoring

* **config:** drop transitional plex_scope legacy validator ([621a2f3](https://github.com/chodeus/chub/commit/621a2f3c7c0d635306ec249374ba15356f3685f5))
* **css:** remove vestigial class labels and fix invented hover classes ([bec60f2](https://github.com/chodeus/chub/commit/bec60f2f29620927cae454ad2c74df8f3596e05d))


### Documentation

* **plan:** backend plan (1/3) for plex_scope + lock match_collections encoding ([0c697d3](https://github.com/chodeus/chub/commit/0c697d376ed124b18f11070425bcda79345e1449))
* **plan:** expand runtime consumer coverage (Task 3b) after Task 1 review ([00c40fe](https://github.com/chodeus/chub/commit/00c40feab369e044525bfd2480f7aa995e457779))
* **plan:** frontend (2/3) + cleanup (3/3) plan for plex_scope ([bf415ef](https://github.com/chodeus/chub/commit/bf415efb33b0ca024be821a583a78232e33ebf98))
* **spec:** central Plex instance + library catalog with per-module plex_scope ([a47a165](https://github.com/chodeus/chub/commit/a47a165ab1b5988f9f381aa18691caadbbabd43a))

## [2.33.0](https://github.com/chodeus/chub/compare/v2.32.0...v2.33.0) (2026-06-21)


### Features

* **css:** migrate frontend from hand-rolled utilities to Tailwind v4 ([8180473](https://github.com/chodeus/chub/commit/818047349ab36a09c0476aa673156cd586762f77))


### Bug Fixes

* **deps:** update all non-major dependencies ([#251](https://github.com/chodeus/chub/issues/251)) ([5ef2764](https://github.com/chodeus/chub/commit/5ef27643f3172d65c155bc6e369152e34befbf4c))
* **deps:** update all non-major dependencies ([#254](https://github.com/chodeus/chub/issues/254)) ([3a9d876](https://github.com/chodeus/chub/commit/3a9d8766ac8f3bca0efd5b3c739f032f764a3ec9))

## [2.32.0](https://github.com/chodeus/chub/compare/v2.31.0...v2.32.0) (2026-06-18)


### Features

* **api:** kometa-assets-scan endpoint + stale toggles in cleanup job ([0349a73](https://github.com/chodeus/chub/commit/0349a737eed84fecdd6fef85976ea876222ea4cd))
* **config:** add poster_cleanarr stale_duplicates settings ([f02a7ce](https://github.com/chodeus/chub/commit/f02a7ce71b9655803fea870cd3bce4dc0407a28a))
* **frontend:** add Orphaned assets section to Poster Cleanarr ([c36c0be](https://github.com/chodeus/chub/commit/c36c0be11a1eac3b76f60119046ba5c0cfe8117c))
* **frontend:** add scanKometaAssets API client method ([aa4f7ed](https://github.com/chodeus/chub/commit/aa4f7ed24fd99723ac554c9a79911344c9d09d84))
* **frontend:** clean-mode Bloat/Stale/Orphan checkboxes ([63d4a3b](https://github.com/chodeus/chub/commit/63d4a3b49cc4eb7fd8fd3458aacf87b0aa981568))
* **frontend:** numbered stale pill + pill legend on Poster Cleanarr ([e257138](https://github.com/chodeus/chub/commit/e2571389591e632052a365ff8331471a0503ab66))
* **library-stats:** report library health instead of poster matches ([f45366a](https://github.com/chodeus/chub/commit/f45366affd4c001ad853e108bc2fff3bfe33da5f))
* **poster-cleanarr:** add VALID_STALE_MODES constant ([c7c0c94](https://github.com/chodeus/chub/commit/c7c0c9422f08a35d5395c60af84a07f1f2d6af11))
* **poster-cleanarr:** build canonical-folder map for stale detection ([1d8ca1c](https://github.com/chodeus/chub/commit/1d8ca1cebfad98f53fe5739f964dcc8cba18149a))
* **poster-cleanarr:** execute stale-duplicate report/move/remove safely ([03bb241](https://github.com/chodeus/chub/commit/03bb241c7bb36407e0d981c6141b28f9e7e217a8))
* **poster-cleanarr:** orchestrate stale-duplicate pass + run() wiring ([73a57df](https://github.com/chodeus/chub/commit/73a57dfdb7458421ae79fc7b635ec910bc5548b4))
* **poster-cleanarr:** scan for stale-duplicate asset folders ([5cafc9f](https://github.com/chodeus/chub/commit/5cafc9f1f925a94ccbe13214938bfbc49dcc91b3))
* **poster-cleanarr:** surface stale-duplicate stats in report + notification ([d1668dd](https://github.com/chodeus/chub/commit/d1668ddeeaa99cb561217390353adf0c1fadd989))
* **search:** match tmdb/tvdb/imdb id in asset and library search ([fb120da](https://github.com/chodeus/chub/commit/fb120da4bc928880504fc4ec1ef6c7fc07a1f8e1))
* **settings:** add poster_cleanarr stale-duplicate settings ([e05d94e](https://github.com/chodeus/chub/commit/e05d94e32e909186c4fcd613a8d8a5cad73679eb))


### Bug Fixes

* **poster-cleanarr:** bound the panel to the viewport so the media list scrolls internally ([2906746](https://github.com/chodeus/chub/commit/2906746b4e666a54785b19e29b5e50043cef35e5))
* **poster-cleanarr:** clarify detail bloat is selected-level scope ([d726a9a](https://github.com/chodeus/chub/commit/d726a9a8ef9a21784ba1d844da4a9180f14610e8))
* **poster-cleanarr:** page through all bundles so tabs show the whole library ([adc0ae3](https://github.com/chodeus/chub/commit/adc0ae3670ee26e75ee93a5e73e03c3d774049d8))
* **poster-renamerr:** re-stage assets when a media folder is renamed ([7165f84](https://github.com/chodeus/chub/commit/7165f842b5dafd51e0bbe444de6085222ec7f936))
* **settings:** default holiday schedule so a new Border Replacerr holiday saves ([68d9db6](https://github.com/chodeus/chub/commit/68d9db6196a0c72407b5c9b5f96de9a497814253))
* **setup:** correct the setup wizard tab title ([414e3d3](https://github.com/chodeus/chub/commit/414e3d37c010ce110a11e6bc4d4b09da974679ce))
* **setup:** hydrate existing Plex/*arr instances in the first-run wizard ([1d98d39](https://github.com/chodeus/chub/commit/1d98d39939ef292bd3b043d38321f2a5055fc864))


### Refactoring

* **poster-cleanarr:** logger param + guard parity + move/both-id tests for stale pass ([bc4da3f](https://github.com/chodeus/chub/commit/bc4da3f576fbe75b94cff1f2c4767075a5d90b2b))


### Documentation

* plan for Poster Cleanarr stale/orphan UI feature ([28f7561](https://github.com/chodeus/chub/commit/28f7561cf39e7f0fc1141278da5da1da93925a5d))
* **poster-cleanarr:** document stale fields in cleanup API + note stale shares orphan instances ([96fffba](https://github.com/chodeus/chub/commit/96fffbac3c79db6f2cd429605e01ce3d4c082e47))

## [2.31.0](https://github.com/chodeus/chub/compare/v2.30.0...v2.31.0) (2026-06-17)


### Features

* **instances:** show live wanted/missing from *arr; drop poster match stats ([58ee1f1](https://github.com/chodeus/chub/commit/58ee1f153b3f71411436dfed2e5e43e746c0c440))
* **notifications:** apply one webhook to multiple modules ([fb31439](https://github.com/chodeus/chub/commit/fb3143927f752cc83a2f2924d2963f6659d8302c))
* **poster-cleanarr:** prune dead symlinks in the orphan pass ([b2241c8](https://github.com/chodeus/chub/commit/b2241c800de70933737eeb00793748ef42c10fee))
* **setup:** first-run setup wizard with a config-aware gate ([483e0b8](https://github.com/chodeus/chub/commit/483e0b8a2f0afb0a5a8660be9ba4b9fc77505647))


### Bug Fixes

* **nohl:** label summary counts as non-hardlinked, not "scanned" ([8c9f4b4](https://github.com/chodeus/chub/commit/8c9f4b440d4793c873e14b4d6aa7f29d3282720a))
* **notifications:** redact webhook URLs and align schema to backend ([685ecd6](https://github.com/chodeus/chub/commit/685ecd679b16b53ad55abaab3d6b57d7f16cb5db))
* **poster-renamerr:** atomic poster copy via temp + os.replace ([7098b92](https://github.com/chodeus/chub/commit/7098b92d014e316e9ba4b5ab945fd8dbb5cdc1f3))
* **renameinatorr:** honour ignore tags across the tag-cycle reset ([6d35bfd](https://github.com/chodeus/chub/commit/6d35bfdef3b6b89bcc06ffdde6c580a795a5d245))
* **unmatched-assets:** count in-library items with a stale unreleased status ([584fc20](https://github.com/chodeus/chub/commit/584fc20accd9c3d9726cfd566ae54941da64095f))

## [2.30.0](https://github.com/chodeus/chub/compare/v2.29.0...v2.30.0) (2026-06-11)


### Features

* **border:** full-library re-border on poster_renamerr run ([#231](https://github.com/chodeus/chub/issues/231)) ([635bf5f](https://github.com/chodeus/chub/commit/635bf5f44faec399f26646df9984cad2a9b6671d))
* **dashboard:** configurable module list and Health section on top ([50efb77](https://github.com/chodeus/chub/commit/50efb77dfafda2131d35613628250ff7c1146476))
* **dashboard:** configurable sections, refresh interval, and Up-next count ([860707e](https://github.com/chodeus/chub/commit/860707e2d5523da5faee16c483910ac532371308))
* **extensions:** backend self-registration framework ([6b4ee12](https://github.com/chodeus/chub/commit/6b4ee12de831dd185b061a8599b3ddeb16784b73))
* **extensions:** frontend self-registration framework ([0e1387c](https://github.com/chodeus/chub/commit/0e1387c84bce9a10120a3fc4609ca6ba960a3c30))
* **gdrive:** bulk-add preset drives and configured sources ([9e77a48](https://github.com/chodeus/chub/commit/9e77a482f590401ed00fd53611fb3b5c88a4baed))
* **posters:** manual artwork picker for logo/background/squareart ([2498919](https://github.com/chodeus/chub/commit/24989199320c25134084d36b53b9124556028174))
* **posters:** warn on year mismatch for ID-matched uploads ([88c8788](https://github.com/chodeus/chub/commit/88c8788c5e4e3c81c10693f7bf55226004b22e3c))
* **renameinatorr:** add refresh-before-rename; fix inert ignore tag ([ffd4d4d](https://github.com/chodeus/chub/commit/ffd4d4dbf204e9b4a3a8f89bcb63d2b771a9b7fb))
* **sync:** restrict gdrive sync to image types and cap file size ([2d45fab](https://github.com/chodeus/chub/commit/2d45fab58efae38b8786e97e9191ae224bd96f18))


### Bug Fixes

* **asset,border:** clear CodeQL alerts (dead code + empty-except comment) ([212124d](https://github.com/chodeus/chub/commit/212124dfdc971bd52ef6a83ec9ae153e64612085))
* **assets:** stop expecting clear logos on seasons ([f91674b](https://github.com/chodeus/chub/commit/f91674b78fa8eda6f8e57789ded2f5b5a1112b0f))
* **auth:** log request path on unauthorized 401s ([37051e9](https://github.com/chodeus/chub/commit/37051e9a1120bc278ea6e0e4a50312f0aa427c1c))
* close audit backlog — redaction gaps, atomic ops, SSRF guard, logging polish ([15c7f33](https://github.com/chodeus/chub/commit/15c7f33c530059a9448bbbd8bdffd196a5a270ae))
* **deps:** update all non-major dependencies ([#225](https://github.com/chodeus/chub/issues/225)) ([71865f0](https://github.com/chodeus/chub/commit/71865f07d3a8d1a7b3be03b3a19ae1bc5549521e))
* **deps:** update all non-major dependencies ([#227](https://github.com/chodeus/chub/issues/227)) ([c9e707b](https://github.com/chodeus/chub/commit/c9e707b918f0400fd9e3cb3743b91b22ff272e7c))
* **fields:** stop leaking non-DOM props onto field elements ([04d19db](https://github.com/chodeus/chub/commit/04d19dbdc9ec303f006ae9648ed387c77959116b))
* harden restore/lookups/tags, add plex-maintenance dry-run + paging ([e409b87](https://github.com/chodeus/chub/commit/e409b87f28716bfb6cb003b503a7ec2b374e1702))
* **plex:** year-disambiguate title matches to prevent wrong-year uploads ([5a97d85](https://github.com/chodeus/chub/commit/5a97d851c109fc0c321175bc31df0250cf72dc1a))
* **plex:** year-disambiguate title matches; log 401 request path ([6946ebd](https://github.com/chodeus/chub/commit/6946ebdafa0c8e3404963cfe7fcac2a129639aff))
* **posters:** make Asset Search poster download actually save a file ([eea5ea4](https://github.com/chodeus/chub/commit/eea5ea4a688c68f4d73e0d1be15d7415b204199b))
* **regex:** factor season delimiter prefix — clears CodeQL unmatchable-caret ([#183](https://github.com/chodeus/chub/issues/183)) ([0fa4aa5](https://github.com/chodeus/chub/commit/0fa4aa546c4eff13a43ff67a9ae4f235122f57dc))
* **security:** close asset-apply path traversal + clear CodeQL test findings ([84eb068](https://github.com/chodeus/chub/commit/84eb06867c6d73d7a335a5526fab0fdf37430fe7))
* **security:** stop world-chmod 777 of CONFIG_DIR; lock down secrets ([58ab510](https://github.com/chodeus/chub/commit/58ab510fe59499532eacc1a090da55e3f21bf498))
* **sync:** drop redundant rclone --exclude that triggered an ERROR log ([f83e38d](https://github.com/chodeus/chub/commit/f83e38d3e3579a7fc265e2bf6d88319f9a2544e1))
* **ui:** honor conditional field visibility in Module Settings ([ee90229](https://github.com/chodeus/chub/commit/ee902291b4151df4a30e445109d8aad49b2f9f86))


### Refactoring

* **border:** remove redundant Holiday-only mode (skip) option ([9dbdeac](https://github.com/chodeus/chub/commit/9dbdeac76e1d6ad5b116a2c50742d1ba00c4468f))


### Documentation

* **settings:** shorten Clean orphan assets tooltip ([f091165](https://github.com/chodeus/chub/commit/f091165e786ce426e136b18b2f8897074d169619))

## [2.29.0](https://github.com/chodeus/chub/compare/v2.28.0...v2.29.0) (2026-06-04)


### Features

* **assets:** wildcard (*) title search in Assets Search ([40161e1](https://github.com/chodeus/chub/commit/40161e148bb21594d83d7aafac386c07b9ff8cff))
* **dashboard:** show per-instance sub-schedules on module status cards ([bc7bdfe](https://github.com/chodeus/chub/commit/bc7bdfe483e1d20bfda3e6122d80b9ce763de3c1))
* **jobs:** per-phase timing for orchestrated module runs ([8e35d65](https://github.com/chodeus/chub/commit/8e35d653160418748c9595fafc4c5a858b72d658))
* **schedule:** surface Upgradinatorr per-instance sub-schedules in UI ([2e248b2](https://github.com/chodeus/chub/commit/2e248b22c351e1b4c1e272364254c7d15c816cda))


### Bug Fixes

* **asset:** fanart is Plex-only (stream, never download); Kometa = g-drive only ([973bd1a](https://github.com/chodeus/chub/commit/973bd1abf4ea7bfd9479d3d14ba265eb55128eb9))
* **logs:** keep container stdout ordered and free of TTY/raw-stdout noise ([cc6cbba](https://github.com/chodeus/chub/commit/cc6cbba9737eb0fd54bf98c6ff33b147a3b8f3aa))
* **logs:** stop double-encoding &lt; and &gt; in the log viewer ([f21cae4](https://github.com/chodeus/chub/commit/f21cae4397a92e3bd84285c0bdf6e1e77225d95c))
* resolve CodeQL alerts (dead assignment, repeated imports) ([54ab470](https://github.com/chodeus/chub/commit/54ab47070de0685b2f8f2cbb0d0e6c217c4179c2))


### Performance

* **asset:** cache fanart.tv URLs (2-day TTL) to kill the per-run refetch storm ([05df4a4](https://github.com/chodeus/chub/commit/05df4a4087aa742dafaa104cc3e68ea5c87741bf))
* **asset:** fold per-image_type local lookups into one fetch ([#3](https://github.com/chodeus/chub/issues/3)) ([846a6cf](https://github.com/chodeus/chub/commit/846a6cf90a3affed76a6588efcbda15ede8ccf64))
* **asset:** preload media_asset_matches + thread-safe fanart client ([55e7543](https://github.com/chodeus/chub/commit/55e7543343e9bf4b7af3ca5104cdcd57c5f9bb3f))
* **asset:** reuse one read connection across the resolve loop (Option A) ([92a4b71](https://github.com/chodeus/chub/commit/92a4b71808378b15b508c45a679830c03be3f7c1))
* **border:** add skip-gate so unchanged posters aren't re-encoded ([2cebe98](https://github.com/chodeus/chub/commit/2cebe98d0331b4d5dea2f8f51c8f41358d6282a3))
* **border:** parallelize processing, atomic same-fs writes, real content compare ([460d4d3](https://github.com/chodeus/chub/commit/460d4d38cb79251c5405d90396f72bc97eb98a40))
* **jobs:** per-phase progress windows so the bar advances through every phase ([fd436e4](https://github.com/chodeus/chub/commit/fd436e44dcb1760559d411bfa8f0c45e0ecd0c0f))
* **match:** skip match-phase row writes when the result is unchanged ([e67ddb8](https://github.com/chodeus/chub/commit/e67ddb851dd9d53b7b50f0505b73102077c9ba20))
* **pipeline:** batch cache writes, honor synchronous=NORMAL, skip redundant gdrive work ([c032bd3](https://github.com/chodeus/chub/commit/c032bd3d33e9464427f2012b47bb34679a54656f))

## [2.28.0](https://github.com/chodeus/chub/compare/v2.27.0...v2.28.0) (2026-06-03)


### Features

* **assets:** index all local assets in Assets Search via search-only rows ([5ecfa13](https://github.com/chodeus/chub/commit/5ecfa13fe2051caa7fcdd395404704151841741d))
* **assets:** sortable unmatched tables + additional-artwork asset search ([d76e687](https://github.com/chodeus/chub/commit/d76e6872ab7b20959e9693f12cf483dbec99d5ba))
* **poster_cleanarr:** separate orphan-asset cleanup from bloat settings ([8cb06f4](https://github.com/chodeus/chub/commit/8cb06f4de90a129b8efcefba1d4e3277d0ef8196))


### Bug Fixes

* **assets:** list all owners/styles regardless of the Image filter ([1b246b1](https://github.com/chodeus/chub/commit/1b246b10a12a078cfd3644dac67cbfa6d83f4195))
* **assets:** render additional artwork with object-contain on a transparency backdrop ([f4c01ae](https://github.com/chodeus/chub/commit/f4c01aecfd7f7375ea407ed21a7c57c94eec90a5))
* **concurrency:** harden parallel runs + fix correctness bugs from today's audit ([c0cd93f](https://github.com/chodeus/chub/commit/c0cd93fda8d82af858225b23d8d26d55a0d8cafc))
* **health:** report DB status via worker so /api/health isn't falsely degraded ([2b8cf3b](https://github.com/chodeus/chub/commit/2b8cf3bb14a324f12682961b0b26f4ba6fd81218))
* **plex:** scope the snapshot TTL guard per-library so labelarr keeps the reuse optimization ([e0f2669](https://github.com/chodeus/chub/commit/e0f266944461b9e1850396f99bd400950640e40b))
* **security:** document intentional empty-except blocks to clear CodeQL notes ([2939344](https://github.com/chodeus/chub/commit/2939344ceeeeccba635cfa7fe3bda41f116e76ff))
* **sync_gdrive:** bind priority on the search-only refresh path ([d10aa7b](https://github.com/chodeus/chub/commit/d10aa7b1b627ca58023e352a9b53fa9975844f56))

## [2.27.0](https://github.com/chodeus/chub/compare/v2.26.2...v2.27.0) (2026-06-02)


### Features

* **asset:** source logos + backgrounds from fanart.tv ([39ca4b1](https://github.com/chodeus/chub/commit/39ca4b1a756e30e7a01758df2a4282b43d64a0b4))
* **cleanarr:** add ID matching + ignore list to orphan asset cleanup ([a581b39](https://github.com/chodeus/chub/commit/a581b3919cb576aa4813c27630bddaa3d601ca46))
* **instances:** show Plex snapshot freshness on instance cards ([1143b65](https://github.com/chodeus/chub/commit/1143b65ef4a1be959785db933317ec26bdd997b7))
* **media-search:** surface external IDs, file name, and richer metadata ([75f2f50](https://github.com/chodeus/chub/commit/75f2f50e3ef5ce37700ab60cf2b4fafcc5280d32))
* **sync:** per-instance sync-completion timestamp for accurate freshness ([0f75382](https://github.com/chodeus/chub/commit/0f753824451b49b2d387db64b79eaf50c66ded9d))
* **unmatched:** add additional-artwork reset + load count on mount ([093173a](https://github.com/chodeus/chub/commit/093173ab2abcc17d1c10a0c0436ce6d27dae88e7))
* **unmatched:** add poster-match reset to the Unmatched page ([54df7d3](https://github.com/chodeus/chub/commit/54df7d3c3fad031dc05841a7b0de0455c7348d6d))
* **unmatched:** make additional-artwork coverage provenance-based ([c3eeb92](https://github.com/chodeus/chub/commit/c3eeb9261902c107624f43d0d0d1cf5c0418d60c))


### Bug Fixes

* **asset_renamerr:** skip release-unready items on the Plex apply path ([f2b8334](https://github.com/chodeus/chub/commit/f2b8334935d86eeb9fa7e10479bfb6eb55cc9f64))
* **jduparr:** use jdupes --json scan, honest link count, and harden run loop ([bdde88c](https://github.com/chodeus/chub/commit/bdde88cddc07a5183b9bd234190f1340eff240bb))
* **nestarr:** make ARR↔Plex unmatched detection opt-in ([499eb8e](https://github.com/chodeus/chub/commit/499eb8e742e1d9e46eb4b8dfebeaeb913a18a2d2))
* **nestarr:** reduce unmatched-assets false positives ([4e96c0e](https://github.com/chodeus/chub/commit/4e96c0e6cef4f387d22b6bc8116c09630eab6b7f))
* **settings:** add fanart.tv module card description ([ca217b3](https://github.com/chodeus/chub/commit/ca217b3f20363051665cf607603b575a0b711a5d))
* **settings:** show the fanart.tv settings section in the UI ([7a94d43](https://github.com/chodeus/chub/commit/7a94d43f4b663747619239beb0c8bec9310e0d2f))


### Performance

* **arr:** parallelize Sonarr/Lidarr sub-item fetching; run upgradinatorr instances concurrently ([2cb2889](https://github.com/chodeus/chub/commit/2cb2889bf8fcd9779e977740467be9437ddbe257))
* eliminate O(n×m)/O(n²) hot loops and parallelize independent I/O ([ed0374e](https://github.com/chodeus/chub/commit/ed0374e2acedc0d46f6bc7a6faeef95c73f9e142))


### Refactoring

* **asset:** drop the fanart.tv response cache ([22bb635](https://github.com/chodeus/chub/commit/22bb635d5089b78865d9619ea4e63210f95c3540))
* **plex:** route all snapshot refreshes through the TTL guard ([5336730](https://github.com/chodeus/chub/commit/5336730a1c19fc9e5c44867cdc16c100ff5d333c))

## [2.26.2](https://github.com/chodeus/chub/compare/v2.26.1...v2.26.2) (2026-06-01)


### Bug Fixes

* **plex:** resolve upload targets by ratingKey, not *arr title ([6aa878a](https://github.com/chodeus/chub/commit/6aa878a7cd0804acae13ca217fad76bacaaf6024))

## [2.26.1](https://github.com/chodeus/chub/compare/v2.26.0...v2.26.1) (2026-06-01)


### Bug Fixes

* **unmatched:** label show season rows in the artwork table ([14c6ad3](https://github.com/chodeus/chub/commit/14c6ad387e168ebc614b9e2ac578fcc962d41d7a))

## [2.26.0](https://github.com/chodeus/chub/compare/v2.25.1...v2.26.0) (2026-06-01)


### Features

* **unmatched:** per-media artwork table + pagination + clickable type cards ([99ebdb7](https://github.com/chodeus/chub/commit/99ebdb7bb39bf682ff3c93a7435c8fff53df7b35))

## [2.25.1](https://github.com/chodeus/chub/compare/v2.25.0...v2.25.1) (2026-06-01)


### Bug Fixes

* **unmatched:** artwork view polish + failure reasons + state-reset endpoint ([38f1887](https://github.com/chodeus/chub/commit/38f1887e0ce3f0e6829031f9e8ede3a96b509eeb))

## [2.25.0](https://github.com/chodeus/chub/compare/v2.24.1...v2.25.0) (2026-06-01)


### Features

* **unmatched:** add Additional-artwork view alongside posters ([f2b1a87](https://github.com/chodeus/chub/commit/f2b1a8736859be946682663fc706e35ad982cfc9))


### Bug Fixes

* **asset_renamerr:** dry-run must not persist match state or log as applied ([266b868](https://github.com/chodeus/chub/commit/266b8685d90739a1a66d99332ce61dd16967a991))

## [2.24.1](https://github.com/chodeus/chub/compare/v2.24.0...v2.24.1) (2026-06-01)


### Performance

* **asset_renamerr:** resolve Plex artwork targets via a shared guid-first index ([bd2b095](https://github.com/chodeus/chub/commit/bd2b095382520db40992e257fc2c4b9c8ec5543f))

## [2.24.0](https://github.com/chodeus/chub/compare/v2.23.0...v2.24.0) (2026-05-31)


### Features

* align poster/asset apply pipeline on a strict Plex|Kometa apply_method ([3f283e2](https://github.com/chodeus/chub/commit/3f283e29f6cb2c7a816e9ddf3c49b51969c0f7ed))

## [2.23.0](https://github.com/chodeus/chub/compare/v2.22.0...v2.23.0) (2026-05-31)


### Features

* **border_replacerr:** surface per-poster failures in the summary (N21) ([196b117](https://github.com/chodeus/chub/commit/196b1178767fb976ab99b10a445da0ab54a23960))


### Bug Fixes

* **asset_renamerr:** per-library backfill for direct asset apply (P7, WS-4) ([b3929c2](https://github.com/chodeus/chub/commit/b3929c278268ca8696e2ae7b54faaf51df4f1942))
* **border_replacerr:** crash-proof holiday parsing + bounds + anchors (WS-3) ([7ff9ce3](https://github.com/chodeus/chub/commit/7ff9ce3f041685a50dd10a2deeced3450881a253))
* **config:** reject invalid action_type/apply_method/count (WS-8) ([1fc661d](https://github.com/chodeus/chub/commit/1fc661da36bd3ec5d58dc57992003338b6105e0b))
* **db:** DB robustness — busy_timeout, rebuild lock, safe ALTER (WS-5) ([e91212b](https://github.com/chodeus/chub/commit/e91212b842fc9d153c79b6fe80d0762adbd44ba1))
* **frontend:** guard stale-data races in useApiData + JobsPage (P31, N28) ([884a6bf](https://github.com/chodeus/chub/commit/884a6bfaf2a67334eb105eb2e5e382f4fd55fd2f))
* **match:** season-poster GUID matching + collection attrs (WS-4 part 1) ([52cc59d](https://github.com/chodeus/chub/commit/52cc59d7ba5b98115ba7ba86593a895f9136ec30))
* **resilience:** ARR/worker/TMDB/Plex-wait robustness (WS-6) ([22a7e12](https://github.com/chodeus/chub/commit/22a7e12af0964261c17c30f468565ccc313f8929))
* **security:** close auth-boundary and secret-exposure gaps (WS-2) ([83bc211](https://github.com/chodeus/chub/commit/83bc211aa194332c15a762a8efe59870957f4075))


### Performance

* **api:** offload blocking handlers off the event loop, part 1 (WS-1) ([cc4abcc](https://github.com/chodeus/chub/commit/cc4abcc063657a43a69365408ee573f72b3f6421))
* **api:** offload duplicate-resolve + duplicate-members handlers (N8, N9) ([2da9ab6](https://github.com/chodeus/chub/commit/2da9ab6c0810f9cdfd479d9616438c106bd77998))
* **api:** offload poster apply/upload/optimize handlers (P2, WS-1) ([7b77aed](https://github.com/chodeus/chub/commit/7b77aed384761f5ec5e46bab7d9bcfa3cf808ec1))
* **api:** offload remaining blocking handlers, part 2 (WS-1) ([e56ba55](https://github.com/chodeus/chub/commit/e56ba5545078218de19726b006f27c27ce8d11cb))
* **labelarr:** build plex mapping once per bulk sync (P3, WS-4) ([1f68506](https://github.com/chodeus/chub/commit/1f685064433de3031ad1b912e4967dcf0ec8484e))

## [2.22.0](https://github.com/chodeus/chub/compare/v2.21.0...v2.22.0) (2026-05-31)


### Features

* **posters:** per-library uploads + skip tracking, unlock manual matches ([816edfe](https://github.com/chodeus/chub/commit/816edfeb91d462194ffc37dd641f9728f4ef31a1))


### Bug Fixes

* orphan pass spares Kometa asset files; asset_renamerr reports progress ([009f68a](https://github.com/chodeus/chub/commit/009f68a314591326cfb1c814c950c9b3d45f2a25))


### Refactoring

* **asset_renamerr:** warn-once on unsupported types + honor print_only_renames ([f7a1fc2](https://github.com/chodeus/chub/commit/f7a1fc25192a80fe2c206bab7eb504884214787b))
* consolidate duplicated logic (fixes clear-logo bloat-deletion bug) ([ce6dfe0](https://github.com/chodeus/chub/commit/ce6dfe06313edac382b5c97931bcd2eeebccdb28))
* remove email notifications (keep Discord + Notifiarr) ([941a62b](https://github.com/chodeus/chub/commit/941a62bf619aeaf5a8be97ac73b2b50aa56adadc))
* **webhook:** consolidate season-scan wait into wait_for_plex_availability ([b51756f](https://github.com/chodeus/chub/commit/b51756fb59fea1543e39ae69127b7347ff726fd6))

## [2.21.0](https://github.com/chodeus/chub/compare/v2.20.1...v2.21.0) (2026-05-31)


### Features

* **asset:** add asset_renamerr for clear logo, square art, background ([bdc6d4a](https://github.com/chodeus/chub/commit/bdc6d4a2abe06d9f14d21d6a97d8a7707fa2e363))
* **upload:** webhook season-scan retry + optional inter-upload throttle ([b30c4a7](https://github.com/chodeus/chub/commit/b30c4a7a42c449d80ba186aadffb891d31e9ec28))


### Bug Fixes

* **match:** auto-match id-less collections, lock manual picks, apply now ([b90e2c3](https://github.com/chodeus/chub/commit/b90e2c3373d83e4e85a417da0f13273a713c166e))
* **ui:** show Asset Renamerr in module settings (CONFIG_MODULE_KEYS) ([a21fa41](https://github.com/chodeus/chub/commit/a21fa4148636331f5c365d9925c95381511d1f65))


### Performance

* **upload:** asset idempotency, mtime fast-path, multi-library, targeted webhooks ([4924080](https://github.com/chodeus/chub/commit/492408046d6a7e568600e1e514cc59d39617c114))

## [2.20.1](https://github.com/chodeus/chub/compare/v2.20.0...v2.20.1) (2026-05-30)


### Bug Fixes

* **deps:** update all non-major dependencies ([#193](https://github.com/chodeus/chub/issues/193)) ([64be1d8](https://github.com/chodeus/chub/commit/64be1d8c1742e4617edee65d034e71a84dc42a8e))
* **deps:** update dependency @tanstack/react-virtual to ^3.13.26 ([#192](https://github.com/chodeus/chub/issues/192)) ([5b21b53](https://github.com/chodeus/chub/commit/5b21b53ef829a55a757ab559ff8143787a88fb19))
* **posters:** rank picker candidates by relevance; restrict picker to Needs Review ([eec28e8](https://github.com/chodeus/chub/commit/eec28e809ee92cdea492ab3f58ce0157a144acd6))
* **sync:** refresh collection ids on re-sync ([36be389](https://github.com/chodeus/chub/commit/36be389dfea1e13f56cc8aaac3d8c88b71af0bf7))
* **sync:** refresh secondary IDs on media re-sync ([a4aeb77](https://github.com/chodeus/chub/commit/a4aeb775f8bb123305355e60ebc18ffa7b2b8b52))
* **sync:** refresh title and year on media re-sync ([aabfbc4](https://github.com/chodeus/chub/commit/aabfbc46971d23bc911816b44bed083c312f2b73))

## [2.20.0](https://github.com/chodeus/chub/compare/v2.19.0...v2.20.0) (2026-05-30)


### Features

* **posters:** manual poster picker + match diagnostics in Unmatched/Review ([b702b6e](https://github.com/chodeus/chub/commit/b702b6ecd864317281607960f32fc9c95947ae5b))


### Bug Fixes

* **posters:** match no-id, article-prefixed titles (e.g. season posters) ([a5227bb](https://github.com/chodeus/chub/commit/a5227bbcb330bbdda07e3ed315b0e81f9e631b0e))
* **posters:** match posters named by an alternate title; add golden match suite ([dd4e5aa](https://github.com/chodeus/chub/commit/dd4e5aa29c8ae91aa5fdcd18e6a345964a4ec738))
* **posters:** match yearless season posters ([a524412](https://github.com/chodeus/chub/commit/a52441215bee0bdf1f33e850907f1d2fb81c047d))
* **posters:** use correct folder-title field in is_match() fallback ([203472c](https://github.com/chodeus/chub/commit/203472c28bd4a4550c7ee62c6a73b4e33af85760))


### Refactoring

* **posters:** remove dead get_prefix; strip {tvdbid-}/{tmdbid-} id blocks ([0ed9e7f](https://github.com/chodeus/chub/commit/0ed9e7f0a8207b573d64d2884359c764f2d989ad))

## [2.19.0](https://github.com/chodeus/chub/compare/v2.18.1...v2.19.0) (2026-05-30)


### Features

* **posters:** "Recently matched" reel ordered by genuine match recency ([fa4e907](https://github.com/chodeus/chub/commit/fa4e907ed0e982155f98e83b63311ce953d8ea6c))


### Bug Fixes

* **tmdb:** don't flag a real id as "not found" on a transient TMDB error ([bfc2d68](https://github.com/chodeus/chub/commit/bfc2d681c77b835f18f47f6f55b4ae51a7543362))

## [2.18.1](https://github.com/chodeus/chub/compare/v2.18.0...v2.18.1) (2026-05-30)


### Bug Fixes

* **posters:** drop blocking Run Match Quality button; refresh tables after ignore/approve ([33fbb44](https://github.com/chodeus/chub/commit/33fbb443d9316fb08d0bdf82397850ee0cba0b4f))
* **posters:** remove no-op refresh button from Unmatched Assets ([5cd1aea](https://github.com/chodeus/chub/commit/5cd1aea9cb4739235371aac62d370c4980410d74))
* **posters:** remove Run Unmatched Assets button from the page ([ae1c06c](https://github.com/chodeus/chub/commit/ae1c06cd327280bd1d8a588d9c8c0f6aaa96ac3f))

## [2.18.0](https://github.com/chodeus/chub/compare/v2.17.0...v2.18.0) (2026-05-30)


### Features

* **posters:** match transparency, review/ignore/conflicts, optional TMDB & fuzzy quality ([4408df2](https://github.com/chodeus/chub/commit/4408df2f5fe313a15d3701aa894da5fe7b88f0f5))


### Bug Fixes

* **posters:** require a delimiter for season tags so a bare "Season N" in a ([4408df2](https://github.com/chodeus/chub/commit/4408df2f5fe313a15d3701aa894da5fe7b88f0f5))

## [2.17.0](https://github.com/chodeus/chub/compare/v2.16.0...v2.17.0) (2026-05-28)


### Features

* **posters:** redesign Unmatched Assets page and relocate recent-synced reel ([998777f](https://github.com/chodeus/chub/commit/998777f1adeb4ddf8bfa4e9ce16bfd475ca480be))

## [2.16.0](https://github.com/chodeus/chub/compare/v2.15.1...v2.16.0) (2026-05-28)


### Features

* **posters:** add applied-poster breakdowns and variant drill-down API ([ae99e2c](https://github.com/chodeus/chub/commit/ae99e2c9705c9795bf2c8dcf13e98e9b00470c39))
* **posters:** add dedicated Unmatched Assets page ([900fa71](https://github.com/chodeus/chub/commit/900fa716be1678d75d7eb8b7f77fda81aff19aad))
* **stats:** revamp poster statistics page ([0b80da8](https://github.com/chodeus/chub/commit/0b80da8067511860ef7be9dbb7197ae588ee8afb))

## [2.15.1](https://github.com/chodeus/chub/compare/v2.15.0...v2.15.1) (2026-05-27)


### Bug Fixes

* **tmdb:** render TMDB section in settings UI ([19852ba](https://github.com/chodeus/chub/commit/19852ba62aca51f16d260ff7c407b4fde74ff1db))

## [2.15.0](https://github.com/chodeus/chub/compare/v2.14.3...v2.15.0) (2026-05-27)


### Features

* **tmdb:** backfill missing media_cache.tmdb_id via TMDB /find ([3ac500b](https://github.com/chodeus/chub/commit/3ac500bdd6739d06919cc7df7f17a6eeb48cdb99))

## [2.14.3](https://github.com/chodeus/chub/compare/v2.14.2...v2.14.3) (2026-05-27)


### Bug Fixes

* **search:** sync bar to URL ?q= on same-route navigation ([c8633a2](https://github.com/chodeus/chub/commit/c8633a290b1c726db03b9f8d13c001685860c518))

## [2.14.2](https://github.com/chodeus/chub/compare/v2.14.1...v2.14.2) (2026-05-27)


### Bug Fixes

* **ui:** show Border Replacerr in browser tab title ([6b9b1a2](https://github.com/chodeus/chub/commit/6b9b1a259463c0a0f9027ff0657c00d73a6d47ec))

## [2.14.1](https://github.com/chodeus/chub/compare/v2.14.0...v2.14.1) (2026-05-27)


### Bug Fixes

* **search:** drive global bar from SearchCoordinator state ([f0ae4a1](https://github.com/chodeus/chub/commit/f0ae4a17ea18e3f5462c3237c089e1cca9214b74))

## [2.14.0](https://github.com/chodeus/chub/compare/v2.13.0...v2.14.0) (2026-05-26)


### Features

* **docker:** support rootless --user and document cap-drop hardening ([bd89fc1](https://github.com/chodeus/chub/commit/bd89fc14122c2fb44513d677b5c6aeb42794e886))
* **posters:** link unmatched titles to assets search ([7dcf9cb](https://github.com/chodeus/chub/commit/7dcf9cb6d55cc7d65b8bccb429364514b8590644))


### Bug Fixes

* **docker:** install jdupes from Debian instead of building from codeberg ([506eb68](https://github.com/chodeus/chub/commit/506eb6854947fdaa6014d698afe156e3630c2aec))
* **logs:** show selected file in dropdown and load full log on open ([28bdf57](https://github.com/chodeus/chub/commit/28bdf573653ce0b726e1d0601795c27a3b83b001))

## [2.13.0](https://github.com/chodeus/chub/compare/v2.12.0...v2.13.0) (2026-05-26)


### Features

* **logging:** standardize per-action + summary logging across modules ([7528512](https://github.com/chodeus/chub/commit/75285120f90cff4e7c3f3e3ecf2fa82c9466c116))
* **ui:** responsive mobile pass across nav, forms, tables, and pickers ([ebc1207](https://github.com/chodeus/chub/commit/ebc1207be67d5759c9e69f3ea05c37bd302ffc43))


### Bug Fixes

* **logger:** switch log timestamps to dd/mm/yyyy 24h ([c8991bc](https://github.com/chodeus/chub/commit/c8991bcf649d99b6869691b75634014d39120fcd))

## [2.12.0](https://github.com/chodeus/chub/compare/v2.11.2...v2.12.0) (2026-05-26)


### Features

* **logging:** per-action lines for sync_gdrive + poster_renamerr ([9d9775f](https://github.com/chodeus/chub/commit/9d9775fe7e798c912094879b19aacb912b2862de))


### Bug Fixes

* **dir-picker:** wire onChange in DirField; skip cache after Create ([1d4b793](https://github.com/chodeus/chub/commit/1d4b7938d55b7ba4c651ff4ae2ef456be4efd41d))

## [2.11.2](https://github.com/chodeus/chub/compare/v2.11.1...v2.11.2) (2026-05-26)


### Bug Fixes

* **sync_gdrive:** browse-roots collapse + root selector + duplicate guard ([4591628](https://github.com/chodeus/chub/commit/45916281588d9a5520af4a7ba209f53d452943a2))
* **system:** drop unused get_allowed_roots import ([f4ad558](https://github.com/chodeus/chub/commit/f4ad5587917e4b94667ba9956027809a8051da7a))

## [2.11.1](https://github.com/chodeus/chub/compare/v2.11.0...v2.11.1) (2026-05-26)


### Bug Fixes

* **dir-picker:** disable Select during initial load or empty path ([cea5b27](https://github.com/chodeus/chub/commit/cea5b277a824c050319e1e6cf49a12e3012067a9))
* **sync_gdrive:** expose container bind mounts; fallback to upstream presets ([7a9118e](https://github.com/chodeus/chub/commit/7a9118ec65eea1429537c5da3b45900fcd935be7))
* **sync_gdrive:** route internal preset fetch through apiCore for auth ([6d14c60](https://github.com/chodeus/chub/commit/6d14c6005eb82008cd9da9d1aab12eddd296f1f0))

## [2.11.0](https://github.com/chodeus/chub/compare/v2.10.0...v2.11.0) (2026-05-25)


### Features

* **sync_gdrive:** bundle CL2K/MM2K presets, prefix names, fix dir picker ([1df83f9](https://github.com/chodeus/chub/commit/1df83f93b3271f8fca12facc05ab61641bc2f308))


### Bug Fixes

* **jobs:** dedupe module_run enqueues and reset Logger start_time per run ([29460e3](https://github.com/chodeus/chub/commit/29460e361338e3c55f60bca8cdfd4f687c4e780d))
* **media:** stop flagging shows with distinct external IDs as folder collisions ([3f5560e](https://github.com/chodeus/chub/commit/3f5560eb3a3920b128d797b0cc9ddef7ce98cc92))

## [2.10.0](https://github.com/chodeus/chub/compare/v2.9.0...v2.10.0) (2026-05-25)


### Features

* **sync_gdrive:** add verbose flag to surface per-file rclone actions ([e026ac8](https://github.com/chodeus/chub/commit/e026ac80efc3594392b2e31dc78f327fb6f8d7ff))


### Bug Fixes

* **dashboard:** point Run a module quick-start to Schedule page ([986407c](https://github.com/chodeus/chub/commit/986407c6dbc6018dc5e8c6e08b9abae21a4cc5d8))
* **docker:** retry codeberg clones with HTTP/1.1 to dodge stream-cancel flakes ([b07f361](https://github.com/chodeus/chub/commit/b07f361fefd8bf8d1e0799b74a9c2631308ded75))
* **jobs:** reflect cross-page run state and persist per-job duration ([6d23ead](https://github.com/chodeus/chub/commit/6d23eadca939582cc7560b368e1d3a84b493bb7c))


### Refactoring

* **notification:** remove unused get_random_joke footer feature ([a856c0a](https://github.com/chodeus/chub/commit/a856c0a6afc2f68f75727675f5d9da4483951f05))
* **poster_renamerr:** restore source_dir bottom-wins, scope orphan pass to destination ([746b996](https://github.com/chodeus/chub/commit/746b996ba5a77986dfda86111dfb8a4cf7d7cb3e))

## [2.9.0](https://github.com/chodeus/chub/compare/v2.8.0...v2.9.0) (2026-05-24)


### Features

* **normalization:** widen poster-title cleanup for ID-less fallback matching ([c0ffbbf](https://github.com/chodeus/chub/commit/c0ffbbf0c5aa7b3a747ef3b51e0860cadce88087))

## [2.8.0](https://github.com/chodeus/chub/compare/v2.7.0...v2.8.0) (2026-05-24)


### Features

* **notifications:** always notify on poster_renamerr, show real transfer deltas for sync_gdrive ([5d49313](https://github.com/chodeus/chub/commit/5d493136077922818a7adb80f901b9c05de58016))


### Bug Fixes

* **media_cache:** use MusicBrainz ID for artist duplicate + collision detection ([a8d43fb](https://github.com/chodeus/chub/commit/a8d43fb05e0a7f1029d3212b8f55a77533a0d223))
* **sync_gdrive:** refresh poster_cache in bulk run() too, not just adhoc ([d90b2c5](https://github.com/chodeus/chub/commit/d90b2c51476007d8a8f0575c4003f5b4fc69cc50))
* **ui:** repair broken header buttons, drop duplicates ([d2bd6db](https://github.com/chodeus/chub/commit/d2bd6db11794813385820c1215b7653c79e2ebfe))


### Refactoring

* **jobs:** collapse sync_gdrive + labelarr dispatch chains to one path each ([eebb5c8](https://github.com/chodeus/chub/commit/eebb5c8c77ea9dae72dc48e6929a767ca8230cda))

## [2.7.0](https://github.com/chodeus/chub/compare/v2.6.0...v2.7.0) (2026-05-24)


### Features

* **notifications:** wire webhook poster_renamerr and bulk labelarr paths ([78734e4](https://github.com/chodeus/chub/commit/78734e433ab4fda28f5bb78a60c46f6cfffe9814))

## [2.6.0](https://github.com/chodeus/chub/compare/v2.5.6...v2.6.0) (2026-05-24)


### Features

* **sync_gdrive:** refresh asset cache per folder, collapse "sync all" to one notifying job ([b436ffd](https://github.com/chodeus/chub/commit/b436ffd266654410ac95de4351ea5c635ef06d9c))

## [2.5.6](https://github.com/chodeus/chub/compare/v2.5.5...v2.5.6) (2026-05-24)


### Bug Fixes

* **media:** identity-based duplicate detection, surface folder collisions ([0ca541a](https://github.com/chodeus/chub/commit/0ca541a7f6ba7b137e9a377fef9c89b436cb66cd))
* **notifications:** pass full ChubConfig to NotificationManager ([7f3c027](https://github.com/chodeus/chub/commit/7f3c0275e92c8f0e3049629fcea0f1a77ca9c452))
* **poster-cache:** mirror disk 1:1, drop title-based row dedup ([3be5dfe](https://github.com/chodeus/chub/commit/3be5dfe8bba1ce224028dc5c41e9dea77faec601))

## [2.5.5](https://github.com/chodeus/chub/compare/v2.5.4...v2.5.5) (2026-05-24)


### Bug Fixes

* **notifications:** wire Discord/Notifiarr/Email end-to-end ([#160](https://github.com/chodeus/chub/issues/160)) ([ad8ad2f](https://github.com/chodeus/chub/commit/ad8ad2fef6831808ad724e1970ec51a13f457316))

## [2.5.4](https://github.com/chodeus/chub/compare/v2.5.3...v2.5.4) (2026-05-23)


### Bug Fixes

* **deps:** update all non-major dependencies ([#150](https://github.com/chodeus/chub/issues/150)) ([128f3a4](https://github.com/chodeus/chub/commit/128f3a47185bcb55ef13e6087008fadfa94ee3f2))
* **docker:** use npm ci so per-arch rolldown bindings resolve from the lockfile ([ebc15b8](https://github.com/chodeus/chub/commit/ebc15b8d277ea1e6e73dd699544ae192754d94e2))

## [2.5.3](https://github.com/chodeus/chub/compare/v2.5.2...v2.5.3) (2026-05-23)


### Bug Fixes

* **settings:** correct source_dirs priority tooltip direction ([#143](https://github.com/chodeus/chub/issues/143)) ([08b9223](https://github.com/chodeus/chub/commit/08b9223ff359fc484f0cf8b4dcc53dadb7dfa3d2))

## [2.5.2](https://github.com/chodeus/chub/compare/v2.5.1...v2.5.2) (2026-05-23)


### Bug Fixes

* **config:** migrate legacy unmatched_assets.instances + surface load failures ([be0e457](https://github.com/chodeus/chub/commit/be0e4572b5cdf7d2094e4208eb8c117e91a329e2))

## [2.5.1](https://github.com/chodeus/chub/compare/v2.5.0...v2.5.1) (2026-05-22)


### Bug Fixes

* **media_cache:** delete stale rows unconditionally on sync ([11698df](https://github.com/chodeus/chub/commit/11698df04142ba467937036d886cbf976e7b8d36))


### Documentation

* **deploy:** add Unraid Community Applications template ([a760938](https://github.com/chodeus/chub/commit/a760938f4ae0e0cd44b425e0a262d095cec64bf9))

## [2.5.0](https://github.com/chodeus/chub/compare/v2.4.0...v2.5.0) (2026-05-22)


### Features

* **border_replacerr:** surface which posters got their borders changed ([2cb5384](https://github.com/chodeus/chub/commit/2cb5384ab812167e49df9395d3442c80cf74ca9a))
* **logger:** add heartbeat() helper for repetitive progress lines ([cbc7ab2](https://github.com/chodeus/chub/commit/cbc7ab26937aee3fe281c10ddd67aa72dddedf31))
* **media-search:** show season badge to distinguish series rows ([cc738e2](https://github.com/chodeus/chub/commit/cc738e2195092cadf99e72aaf8aecb472d9a0128))
* **modules:** wire job-progress reporting into ChubModule base ([ebf4ce1](https://github.com/chodeus/chub/commit/ebf4ce106813820a84adfcf32649d82b65f713f1))
* **poster_renamerr:** heartbeat progress during merge_assets phase ([a69be18](https://github.com/chodeus/chub/commit/a69be18a8e8925f64072bafa0b8d3e228a972a6f))
* **poster_renamerr:** report progress across match + rename phases ([fe8e3e5](https://github.com/chodeus/chub/commit/fe8e3e54d44e1ec43eecebed33abcd85d0cba4dc))


### Bug Fixes

* **connector:** propagate per-season monitored flag ([61ec442](https://github.com/chodeus/chub/commit/61ec442458b3063af3e523738c04c9c009b09bb5))
* **logs:** Debug toggle visible state + per-line search ([4b689ed](https://github.com/chodeus/chub/commit/4b689ed4087b2e5a40167c7280f67bf83e28decc))
* **logs:** use existing 'Hide heartbeat' toggle instead of DEBUG demotion ([487ad74](https://github.com/chodeus/chub/commit/487ad74b9292722746c4f8d4cb8ebcff3355460f))
* **media_cache:** normalize search query ([02b6e61](https://github.com/chodeus/chub/commit/02b6e61ef23a9c7e0b806d5c821ea5cb57f51663))
* **notification:** defensive cast on Notifiarr channel_id ([9dbd1a0](https://github.com/chodeus/chub/commit/9dbd1a0a81774740dd21bf3849ec4a6d6a8ea824))
* **poster_renamerr:** drop double-s in 'No &lt;type&gt; to rename' log line ([323f4cd](https://github.com/chodeus/chub/commit/323f4cdbe9a07b699892eded8f48633871f1a7e5))
* **unmatched_assets:** use episodeFileCount, link Discord request to season ([908015a](https://github.com/chodeus/chub/commit/908015a62119a9237166fcac85294a5b96c0e1db))

## [2.4.0](https://github.com/chodeus/chub/compare/v2.3.0...v2.4.0) (2026-05-22)


### Features

* **api:** /system/db-stats, /system/db/vacuum, /system/db/poster-cache/clear ([30b5b22](https://github.com/chodeus/chub/commit/30b5b223b52dcda38d967824e896c04bc3072598))
* **settings:** System page for DB stats and maintenance ([b2097c1](https://github.com/chodeus/chub/commit/b2097c11d9a56d01cc86dca41d385e52b50e0f84))
* **ui:** jump-to-page select on paginated list views ([4857db1](https://github.com/chodeus/chub/commit/4857db1d032f3ee912ed648763451f1c9fc36dbf))


### Bug Fixes

* **frontend:** clipboard copy works on plain-HTTP LAN deployments ([bb16c44](https://github.com/chodeus/chub/commit/bb16c442d62b52b3383fb6270980441eed76460a))
* **poster_cache:** normalize search query for hyphenated titles ([75ea2e8](https://github.com/chodeus/chub/commit/75ea2e8367d7fae60dbcb6bb0b40675d07615807))
* **poster_renamerr:** don't strip singular 'Special' from movie titles ([ed3717d](https://github.com/chodeus/chub/commit/ed3717d58ab0ce3d2c6ba3dc907891eddf7c45ae))
* **schema:** purge orphan poster_cache rows from the Specials regex bug ([75987b0](https://github.com/chodeus/chub/commit/75987b0392d114c31d32d7cee1f1dd870c200056))
* **unmatched_assets:** drop announced/tba items via *arr status field ([a014053](https://github.com/chodeus/chub/commit/a0140536cbdd4603ebef5778e222ae6e3e7328f7))

## [2.3.0](https://github.com/chodeus/chub/compare/v2.2.1...v2.3.0) (2026-05-21)


### Features

* **config:** auto-migrate legacy YAML config shapes on load ([5f057a7](https://github.com/chodeus/chub/commit/5f057a70fb449045a767958d3a752d3de0122fd2))
* **settings/sync_gdrive:** hide OAuth fields when service-account file is set ([ecf17ca](https://github.com/chodeus/chub/commit/ecf17ca6b71af735a80127025a28ae517557b22f))
* **settings/sync_gdrive:** surface dry_run at the top of the page ([dd697b6](https://github.com/chodeus/chub/commit/dd697b61ea399df5c84d2b9ee21d9491ce5aca87))


### Documentation

* **config-migrator:** remind users to verify path-typed fields after migration ([f59acac](https://github.com/chodeus/chub/commit/f59acac721075f04788bdd9e67fcf88cc5dc3a3a))
* **readme:** point at the auto-migration section for older configs ([38eabc2](https://github.com/chodeus/chub/commit/38eabc22ce7048640d59bebc0d4fd850d66386b1))

## [2.2.1](https://github.com/chodeus/chub/compare/v2.2.0...v2.2.1) (2026-05-21)


### Bug Fixes

* **tests:** silence py/empty-except via contextlib.suppress in teardown ([f3ff39c](https://github.com/chodeus/chub/commit/f3ff39c3d993bc7ca32c512d4b587ff051aadbb1))
* **unmatched_assets:** track tmdb-vs-tvdb via return value, not URL substring ([8e1ddfb](https://github.com/chodeus/chub/commit/8e1ddfbaa2d4da997af5b854e1823276308d0f46))

## [2.2.0](https://github.com/chodeus/chub/compare/v2.1.0...v2.2.0) (2026-05-21)


### Features

* **unmatched_assets:** copy Discord poster-request block per row ([3543fd1](https://github.com/chodeus/chub/commit/3543fd1206572eace38b9313393e1860a622100e))


### Bug Fixes

* **deps:** update all non-major dependencies ([#126](https://github.com/chodeus/chub/issues/126)) ([77053e0](https://github.com/chodeus/chub/commit/77053e0d2229f67a5419268b727d5055dd47c0dd))
* **unmatched_assets:** hide unreleased seasons + movies, tighten log output ([c251c58](https://github.com/chodeus/chub/commit/c251c58ae1ddf3cc5a25efa21a58d5297bb48606))

## [2.1.0](https://github.com/chodeus/chub/compare/v2.0.1...v2.1.0) (2026-05-13)


### Features

* **settings:** surface Border Replacerr path + color fields, update Renamerr orphan copy ([edd699c](https://github.com/chodeus/chub/commit/edd699c9da67f345735817a4f6a32e51d56402b4))


### Refactoring

* **poster_renamerr:** drop duplicate orphan_assets_mode, defer to poster_cleanarr ([c243726](https://github.com/chodeus/chub/commit/c24372603e53656b36c6599e072d35407afe99b0))

## [2.0.1](https://github.com/chodeus/chub/compare/v2.0.0...v2.0.1) (2026-05-13)


### Bug Fixes

* **dashboard:** compare health snapshot status to 'healthy', not 'ok' ([40e132b](https://github.com/chodeus/chub/commit/40e132b0adf6d719a8cf0e47131fb3a4524aaf22))
* **instances_field:** handle config-style Plex items in toggle/library handlers ([add2f5b](https://github.com/chodeus/chub/commit/add2f5b402584b75440ce7dcd192c268c418f7c3))


### Refactoring

* **settings:** move log_level/dry_run to top of poster_renamerr + border_replacerr ([77d0396](https://github.com/chodeus/chub/commit/77d03969e989a472e185ddbd332b9eee016a88bd))


### Documentation

* **upgradinatorr:** clarify the Enabled profile toggle copy ([ea73080](https://github.com/chodeus/chub/commit/ea73080caadba41174c5a850bc5c165016031a72))

## [2.0.0](https://github.com/chodeus/chub/compare/v1.15.4...v2.0.0) (2026-05-13)


### ⚠ BREAKING CHANGES

* **db:** /api/webhooks/cleanarr/status and /api/webhooks/cleanarr/process are removed. External callers wired to those URLs will now 404.
* **poster_cleanarr:** poster_renamerr.run_cleanarr is removed (no backcompat alias). Existing configs need to set clean_orphan_assets instead.

### Features

* **poster_cleanarr:** add orphan-asset cleanup; rename ledger to pending_deletions ([777a991](https://github.com/chodeus/chub/commit/777a9912883e2f68c70cc580ea451e65fa177668))
* surface previously-unused DB data across dashboard, posters, and media ([28e22c6](https://github.com/chodeus/chub/commit/28e22c67cb0713a148343344977fd730ad74edf6))


### Bug Fixes

* **poster_collections:** finish the half-wired integration ([3e6da88](https://github.com/chodeus/chub/commit/3e6da88a16d11ec7834c30a90ca0e6be58cd9712))


### Refactoring

* **db:** rip out the pending-deletions ledger ([c5c1a1e](https://github.com/chodeus/chub/commit/c5c1a1eec8f5fce82d34efb6425f707147648c55))
* **modules:** simplify dry-run controls for health_checkarr and unmatched_assets ([bb33707](https://github.com/chodeus/chub/commit/bb33707e7f79bec4bdb7d41a2bb35a0b77e36bd5))

## [1.15.4](https://github.com/chodeus/chub/compare/v1.15.3...v1.15.4) (2026-05-13)


### Bug Fixes

* **poster_cleanarr:** bump scan timeout to 120s, prune deleted paths on job success ([d8b11ba](https://github.com/chodeus/chub/commit/d8b11bacf996faa9c3f4911ed7abad3c2b214ca2))

## [1.15.3](https://github.com/chodeus/chub/compare/v1.15.2...v1.15.3) (2026-05-13)


### Bug Fixes

* **assets:** keep title on card, show IDs on tighter second line ([f2cd43b](https://github.com/chodeus/chub/commit/f2cd43bd3dc529c1b7d902c50adda817fd2b829b))
* **assets:** show full filename under poster, register no-op search handler ([e69ee45](https://github.com/chodeus/chub/commit/e69ee451b88eff1d5f946212a66ca5a46a38e56d))

## [1.15.2](https://github.com/chodeus/chub/compare/v1.15.1...v1.15.2) (2026-05-13)


### Bug Fixes

* **assets:** show full filename and pin owner name to card bottom ([bf7f980](https://github.com/chodeus/chub/commit/bf7f9809526de8e5fba568fd0f998928f89cf036))

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
