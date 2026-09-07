# Changelog

All notable changes to CHUB are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.48.1](https://github.com/chodeus/chub/compare/v2.48.0...v2.48.1) (2026-08-30)


### Bug Fixes

* **version:** stamp BUILD_NUMBER into release-built images ([bc3bc1a](https://github.com/chodeus/chub/commit/bc3bc1afeea0cf8b55960621aa68bf0e3350f799))

## [2.48.0](https://github.com/chodeus/chub/compare/v2.47.0...v2.48.0) (2026-08-29)


### Features

* **artwork:** align asset handling with Kometa's asset-naming spec ([#593](https://github.com/chodeus/chub/issues/593)) ([03a1f30](https://github.com/chodeus/chub/commit/03a1f3015ddf614f1109db84d1a7dc70a6fc73fa))
* **cl2k:** mirror the artwork horizontally ([#579](https://github.com/chodeus/chub/issues/579)) ([712c86b](https://github.com/chodeus/chub/commit/712c86b847514b378e1f2c3cd2ae64a264af38e8))
* **sync_gdrive:** clean up folders left behind by removed drives ([#594](https://github.com/chodeus/chub/issues/594)) ([4f32c3f](https://github.com/chodeus/chub/commit/4f32c3f57bef558710d6ba3571e817313807378d))
* **sync_gdrive:** warn when syncs fall back to rclone's shared client_id ([#591](https://github.com/chodeus/chub/issues/591)) ([58e63e7](https://github.com/chodeus/chub/commit/58e63e7ca3b3f4ae1208d218f4df5dad8cf48fea))


### Bug Fixes

* **assets:** classify Kometa's foldered bare stems by type, not as posters ([#595](https://github.com/chodeus/chub/issues/595)) ([0e5ddd8](https://github.com/chodeus/chub/commit/0e5ddd88e87085a40de30cbaa2941997fc8cf614))
* **cl2k:** scope season backdrop reuse to the series, not any tmdb id ([#592](https://github.com/chodeus/chub/issues/592)) ([d239a1f](https://github.com/chodeus/chub/commit/d239a1f501f708685dd6792ae516dd05455b89f6))
* **config:** don't cache a config whose preset reconcile failed ([20cb400](https://github.com/chodeus/chub/commit/20cb400613ff2653f0113c32d6959ca738402808))
* dead gdrive presets and tmdb movie/TV namespace collisions ([#590](https://github.com/chodeus/chub/issues/590)) ([60ecad1](https://github.com/chodeus/chub/commit/60ecad1fa96903bb6f3df00d12b4be02297766f1))
* **deps:** update all non-major dependencies ([7c086b0](https://github.com/chodeus/chub/commit/7c086b07a86fdc50f7eb27adf994d7ca68431558))
* **deps:** update all non-major dependencies ([5e5476a](https://github.com/chodeus/chub/commit/5e5476a09fc9edc6bbc04bcc482b347bdddd572f))
* **deps:** update all non-major dependencies ([#585](https://github.com/chodeus/chub/issues/585)) ([5e5476a](https://github.com/chodeus/chub/commit/5e5476a09fc9edc6bbc04bcc482b347bdddd572f))
* **deps:** update all non-major dependencies ([#600](https://github.com/chodeus/chub/issues/600)) ([7c086b0](https://github.com/chodeus/chub/commit/7c086b07a86fdc50f7eb27adf994d7ca68431558))
* **notifications:** cap every listing at 50 items and always tally ([b854de8](https://github.com/chodeus/chub/commit/b854de88a0c426e39f8e20250e504d1a0fd13bf3))
* **notifications:** send summaries, not the run log's debug detail ([269390d](https://github.com/chodeus/chub/commit/269390d0088519a89c199a7bb974cfd4a2aa318b))
* report downloads stuck awaiting import, and harden *arr response handling ([#589](https://github.com/chodeus/chub/issues/589)) ([082f48c](https://github.com/chodeus/chub/commit/082f48cdd401840eee98309374de6a6cd89d199a))
* **upgradinatorr:** drop manual-import noise from the run log ([ebf0c4e](https://github.com/chodeus/chub/commit/ebf0c4ef6d60541aa5edc45aeab2aefedfa5b744))
* **upgradinatorr:** reduce the queue sections to a tally at info ([1968d88](https://github.com/chodeus/chub/commit/1968d884f1144e6dc5524e27aacdb5317784c04b))
* **version:** check for updates against the published image, not commit count ([#587](https://github.com/chodeus/chub/issues/587)) ([937cc34](https://github.com/chodeus/chub/commit/937cc34e5755ef9c18c74b073321b96d4b3c16d4))


### Refactoring

* **cl2k:** bundle the six framing knobs into one Framing object ([#582](https://github.com/chodeus/chub/issues/582)) ([b74948b](https://github.com/chodeus/chub/commit/b74948b5bf46d84f52928dd9ec93aadbf6d468f5))


### Documentation

* BUILD_NUMBER is load-bearing, not decoration ([7bb617b](https://github.com/chodeus/chub/commit/7bb617bf8240e7e5c6ea1a0da60237b4bb4cee2b))
* drop the last develop-era references ([eec28cd](https://github.com/chodeus/chub/commit/eec28cda3ffd6e0778d21bc47553052bc40223a0))

## [2.47.0](https://github.com/chodeus/chub/compare/v2.46.1...v2.47.0) (2026-08-18)


### Features

* one branch, two images — :latest lean, :full with extensions ([#577](https://github.com/chodeus/chub/issues/577)) ([03ba390](https://github.com/chodeus/chub/commit/03ba39085b299f94865a86db3d4a17d31ae72b14))


### Bug Fixes

* **cl2k:** as-is handlers respect unmount; effects abort their requests ([03ba390](https://github.com/chodeus/chub/commit/03ba39085b299f94865a86db3d4a17d31ae72b14))
* **ui:** touch follow-ups — shared SegmentedControl, min-w pins, grid density ([#575](https://github.com/chodeus/chub/issues/575)) ([bf4bc1f](https://github.com/chodeus/chub/commit/bf4bc1f8b634e912d62915fc484f419f3d12834d))


### Refactoring

* **db:** scheduler health writes move behind SystemHealth ([#572](https://github.com/chodeus/chub/issues/572)) ([d1fb773](https://github.com/chodeus/chub/commit/d1fb7737116db61d9a43d068f414518773088a59))

## [2.46.1](https://github.com/chodeus/chub/compare/v2.46.0...v2.46.1) (2026-08-17)


### Bug Fixes

* **security:** allowed-roots gap-fill; thumbnail and download confined ([#534](https://github.com/chodeus/chub/issues/534)) ([158787b](https://github.com/chodeus/chub/commit/158787b36d998b4668465d124814d48eaa036b64))
* **security:** confine and anchor every cleanup delete ([#540](https://github.com/chodeus/chub/issues/540)) ([171227b](https://github.com/chodeus/chub/commit/171227b4d7c085fabee53b0fdcae3718caebfb78))
* **ui:** 44px touch batch + vendor icon layer + dvh truth ([#526](https://github.com/chodeus/chub/issues/526)) ([c863872](https://github.com/chodeus/chub/commit/c86387269c69845fb28f0d6671ed2cf1574681e5))
* **ui:** device touch pass — real geometry for the deferred controls ([#533](https://github.com/chodeus/chub/issues/533)) ([227f22f](https://github.com/chodeus/chub/commit/227f22f78596ae3484176a47ca7b53d8a09c9287))


### Refactoring

* **api:** media_api queries move behind named interface methods ([#523](https://github.com/chodeus/chub/issues/523)) ([1b6dc2d](https://github.com/chodeus/chub/commit/1b6dc2d25f1640b6c67c467d36cdb31fff539fa0))
* **api:** posters router splits into a package by resource ([#541](https://github.com/chodeus/chub/issues/541)) ([8b647fd](https://github.com/chodeus/chub/commit/8b647fd049be8342b902d6862e7aaa36e8db3605))
* **api:** posters.py queries move behind named interface methods ([#527](https://github.com/chodeus/chub/issues/527)) ([0a86f89](https://github.com/chodeus/chub/commit/0a86f89ecc3ba2bf7dbfadd5009bd8e8e3df492c))
* **api:** posters.py stage 2 — non-route logic moves to util owners ([#536](https://github.com/chodeus/chub/issues/536)) ([de0e3eb](https://github.com/chodeus/chub/commit/de0e3eb655e010a6450f19bef7b0971c76973bf2))
* **api:** system/jobs/modules/instances SQL moves behind interfaces ([#535](https://github.com/chodeus/chub/issues/535)) ([940e525](https://github.com/chodeus/chub/commit/940e525977160ef7feef0879b220f3946c1adb94))
* **db:** media_cache splits into domain mixins ([#531](https://github.com/chodeus/chub/issues/531)) ([0f068df](https://github.com/chodeus/chub/commit/0f068df08e85e22d2ea88624f1840a40f204f9e6))

## [2.46.0](https://github.com/chodeus/chub/compare/v2.45.0...v2.46.0) (2026-08-13)


### Features

* **cl2k:** add a connection test for the AI provider ([#487](https://github.com/chodeus/chub/issues/487)) ([c07501e](https://github.com/chodeus/chub/commit/c07501e4f8d9ebdf6e78e03f757e101d3f916939))
* **cl2k:** key logos out of busy art with the AI erase route ([#481](https://github.com/chodeus/chub/issues/481)) ([982bec0](https://github.com/chodeus/chub/commit/982bec08415c77af9d6779f2616665bbc13bd451))
* **gdrive-presets:** add new preset 'Chodeus' to gdrive_presets.json ([ec01576](https://github.com/chodeus/chub/commit/ec015761bc1d05432acfdfc4c58b690ab2116c50))
* **logging:** one designed redaction layer for all log output ([#521](https://github.com/chodeus/chub/issues/521)) ([25c2153](https://github.com/chodeus/chub/commit/25c2153e1df4454e834953721e15155452ab5794))


### Bug Fixes

* **api:** cap every JSON body read app-wide; renovate python gate tells the truth ([#518](https://github.com/chodeus/chub/issues/518)) ([a36fb2a](https://github.com/chodeus/chub/commit/a36fb2ada3bbe94aecf9ca3b3e9f21548ac22de6))
* **api:** keep exception text out of response bodies; break the logger import cycle ([#511](https://github.com/chodeus/chub/issues/511)) ([0244bfa](https://github.com/chodeus/chub/commit/0244bfab12680fe19376095e167eaa4feff9a82e))
* **api:** poster preview authorizes the resolved path (closes code-scanning 297) ([#520](https://github.com/chodeus/chub/issues/520)) ([bf965e9](https://github.com/chodeus/chub/commit/bf965e91947372f9c80a481431aaab7908452bf4))
* **api:** poster preview authorizes the resolved path (CodeQL 297) ([bf965e9](https://github.com/chodeus/chub/commit/bf965e91947372f9c80a481431aaab7908452bf4))
* **backend:** correctness + perf batch (STATIC_DIR, LIKE escaping, fail-open guards, hot-path caching) ([#506](https://github.com/chodeus/chub/issues/506)) ([7881bff](https://github.com/chodeus/chub/commit/7881bffc1ca7c160524addb62771ae6220578e1e))
* **ci:** correct branch-image workflow across the board ([#504](https://github.com/chodeus/chub/issues/504)) ([4155bc5](https://github.com/chodeus/chub/commit/4155bc52b2759b75ebdaf84f85c12d16263d0c6f))
* **ci:** develop-invariant guard — pure-insertion Dockerfile check, not byte-prefix ([#505](https://github.com/chodeus/chub/issues/505)) ([b3a2b59](https://github.com/chodeus/chub/commit/b3a2b5908627c826d92b74b44e4088b9a5c91523))
* **cl2k:** defer artwork uploads like posters, and report deferred failures ([#491](https://github.com/chodeus/chub/issues/491)) ([abb2fc3](https://github.com/chodeus/chub/commit/abb2fc39d9c1f015d5e5c8844ef324e375ce11cf))
* **cl2k:** extract mixed white+coloured titles in subject mode ([#477](https://github.com/chodeus/chub/issues/477)) ([bc8b809](https://github.com/chodeus/chub/commit/bc8b80934227580b790189a14b02b9b0feae990b))
* **cl2k:** stop concurrent Drive uploads creating duplicate files ([#490](https://github.com/chodeus/chub/issues/490)) ([cc2b236](https://github.com/chodeus/chub/commit/cc2b23680a9fc8b7cf384fd470bb847c33033087))
* **cl2k:** withhold Detect text unless the sidecar can serve it ([#484](https://github.com/chodeus/chub/issues/484)) ([26edbf8](https://github.com/chodeus/chub/commit/26edbf87981bdb0819a5bb22cefcfeacff13be6c))
* **frontend:** dead Tailwind classes + used-vs-emitted CI guard, dev-route gating, dead code sweep ([#507](https://github.com/chodeus/chub/issues/507)) ([0a15020](https://github.com/chodeus/chub/commit/0a150200776051fe581d896b5ae647fc3bcd8028))
* **frontend:** follow-up micro-batch — abortable browsePosters, deferred revokes, response docs ([#515](https://github.com/chodeus/chub/issues/515)) ([ed351d9](https://github.com/chodeus/chub/commit/ed351d9c7fc36a9d7fb46aa6f7aa1126f0c26e2a))
* **frontend:** follow-up micro-batch — abortable browsePosters, safe downloads, honest response docs ([ed351d9](https://github.com/chodeus/chub/commit/ed351d9c7fc36a9d7fb46aa6f7aa1126f0c26e2a))
* **gdrive-presets:** add the missing comma before the Chodeus artwork drive ([d0ff8d4](https://github.com/chodeus/chub/commit/d0ff8d47c818b40a837c810cc443992e5e8dce64))
* **ui:** login password-toggle overlap (root cause) + mobile compatibility pass ([#517](https://github.com/chodeus/chub/issues/517)) ([6d7783f](https://github.com/chodeus/chub/commit/6d7783fe5b3997b6cd06b1bac5d58e9ac875e3de))

## [2.45.0](https://github.com/chodeus/chub/compare/v2.44.0...v2.45.0) (2026-08-07)


### Features

* **unmatched:** group the Ignored tab by show, like Unmatched ([#463](https://github.com/chodeus/chub/issues/463)) ([d73d4fe](https://github.com/chodeus/chub/commit/d73d4feba254587ba14ebe82987d69aad361a81b))
* **unmatched:** let a series row ignore one season instead of all of them ([#458](https://github.com/chodeus/chub/issues/458)) ([3e2a0a5](https://github.com/chodeus/chub/commit/3e2a0a528024ecaf629f4b33ece6c956936e8581))


### Bug Fixes

* **api:** let a caller's AbortSignal actually cancel a request ([#468](https://github.com/chodeus/chub/issues/468)) ([293eb57](https://github.com/chodeus/chub/commit/293eb572ae8eced4a8ca3e4a310c9d7afbe3655c))
* **api:** name the offending fields on a validation error ([#474](https://github.com/chodeus/chub/issues/474)) ([24b7563](https://github.com/chodeus/chub/commit/24b7563d064c7dc9316676123d32f23b61bc9817))
* **deps:** bump js-yaml to 4.3.1 for GHSA-5p4m-2wfm-xmqj ([#461](https://github.com/chodeus/chub/issues/461)) ([393b5c0](https://github.com/chodeus/chub/commit/393b5c00dc36e30df5d06e287cc2df1b74864e7b))
* **poster-cleanarr:** bypass the GET cache on status polls ([#451](https://github.com/chodeus/chub/issues/451)) ([3594e3b](https://github.com/chodeus/chub/commit/3594e3bf58af8557dc1396f4026c8ffbc9542c7f))
* **poster-cleanarr:** protect collection and people artwork from the bloat scan ([#454](https://github.com/chodeus/chub/issues/454)) ([3817802](https://github.com/chodeus/chub/commit/3817802c45e76b2318a04acf486f35ca708df86a))
* **unmatched:** restore row actions on series, split grouped rows per instance ([#456](https://github.com/chodeus/chub/issues/456)) ([669533c](https://github.com/chodeus/chub/commit/669533c3ee444394856e407e24c0a119fcf40b67))

## [2.44.0](https://github.com/chodeus/chub/compare/v2.43.3...v2.44.0) (2026-08-05)


### Features

* **backup:** configurable backup location ([342c116](https://github.com/chodeus/chub/commit/342c11638d5b064ecb45804a99b040f6c75de6d3))
* **gdrive-presets:** add the 8 community artwork drives ([f66b013](https://github.com/chodeus/chub/commit/f66b0131d0276c975bcf14e8dc06f9df6c2cfb1a))


### Bug Fixes

* address review findings on the backup and Plex identity changes ([81e547d](https://github.com/chodeus/chub/commit/81e547decdf354a59e302c358ed76266c4831c97))
* **deps:** pin brace-expansion 1.1.18, dropping the obsolete OSV exception ([692e4c5](https://github.com/chodeus/chub/commit/692e4c5dc08bd2eb6361aa362ab0c1e005a80a5e))
* **deps:** update all non-major dependencies ([#433](https://github.com/chodeus/chub/issues/433)) ([da9e780](https://github.com/chodeus/chub/commit/da9e780e32ec714a6b91e900904cbab60066500f))
* **deps:** update fast-uri to 3.1.5 (GHSA-7p8r-x3mc-p8w7) ([723b038](https://github.com/chodeus/chub/commit/723b038c3aef2f3d37675cc51e77159072987882))
* **logs:** stop the viewer collapsing after the first poll ([fa9151c](https://github.com/chodeus/chub/commit/fa9151cb2c724f90900232bf122b017c7c89b449))
* **maintenance:** unlink the backup entry itself, never a link target ([3a350ff](https://github.com/chodeus/chub/commit/3a350ff8126942336ae98cd3a78e76f74636080e))
* **plex:** pin a stable Plex client identity ([85830f8](https://github.com/chodeus/chub/commit/85830f8d83383f2ea442112e6b6e6ba9b541f348))
* **renamer:** don't type an IMDb-tagged year-less file as a collection ([e10d8ac](https://github.com/chodeus/chub/commit/e10d8ac98e4339cf7ecfd595b42443ca81458c96))
* **upgradinatorr:** scope Lidarr album grab history to the album ([283a517](https://github.com/chodeus/chub/commit/283a5174c2de9d2ffe572e125547f84a69bd80cc))


### Performance

* **db:** drop unselective poster_cache indexes and run ANALYZE ([5b795db](https://github.com/chodeus/chub/commit/5b795db2b0bb2f88166c955be3d3efc7f92eae40))


### Documentation

* **presets:** note that square art is Plex-only in the picker description ([a509ec3](https://github.com/chodeus/chub/commit/a509ec38ab57928fb5e411bc646b06b86400942f))

## [2.43.3](https://github.com/chodeus/chub/compare/v2.43.2...v2.43.3) (2026-07-31)


### Bug Fixes

* **arr:** raise the run budget to an hour on observed evidence ([f5a9fad](https://github.com/chodeus/chub/commit/f5a9fadce4707f2827b56a8d3812852efb93c490))
* **arr:** treat a non-dict poll response as a poll error, not a crash ([33d2cdb](https://github.com/chodeus/chub/commit/33d2cdbbfe123764b400df6d910c0cd25f1e15dc))
* **auth:** route rejected fetches through the retry gate ([cc4ce05](https://github.com/chodeus/chub/commit/cc4ce05c4e7b9ffec9fa4604436b294a01a47cf3))
* **auth:** stop the stream-token 401 retry loop ([914b9ce](https://github.com/chodeus/chub/commit/914b9cebfa068edd359fa69a0fa4a930374c2317))
* close the DB-context leak and make rotation paths directory-safe ([b0d40ff](https://github.com/chodeus/chub/commit/b0d40ffb5a529394ce9e4118761395abc72f4b2b))
* harden env parsing and correct the deferred-item tag count ([8b1441f](https://github.com/chodeus/chub/commit/8b1441fcd5ccc0a5774eba1266e10bc8270b2c17))
* **logger:** cap log file size and keep buffered event times ([9db2968](https://github.com/chodeus/chub/commit/9db29680c74f32d02f22338bd41c9459c2ab79f0))
* stop retrying handled 401s and fail closed on an unreadable command list ([bce3efc](https://github.com/chodeus/chub/commit/bce3efcc6044402c6aa3792daa45de3169ee2389))
* stop the stream-token retry loop, cap log size, and fix arr command waits ([1c2920f](https://github.com/chodeus/chub/commit/1c2920fe74f7df32db5e11d3b9a8fd1d6b146565))
* **upgradinatorr:** budget arr queue time separately from run time ([537f39c](https://github.com/chodeus/chub/commit/537f39c33378edc7aa8e074c8762a1830df3fa87))

## [2.43.2](https://github.com/chodeus/chub/compare/v2.43.1...v2.43.2) (2026-07-30)


### Bug Fixes

* **docker:** build the frontend on the native platform, not under QEMU ([#416](https://github.com/chodeus/chub/issues/416)) ([7009ea6](https://github.com/chodeus/chub/commit/7009ea68443a8335a0cfc6bc38bf84b7577cbc0d))

## [2.43.1](https://github.com/chodeus/chub/compare/v2.43.0...v2.43.1) (2026-07-29)


### Bug Fixes

* **ui:** make the app usable in real mobile browsers ([#410](https://github.com/chodeus/chub/issues/410)) ([ffcb6cd](https://github.com/chodeus/chub/commit/ffcb6cde6f64522f47744edff0db2fb621b6b007))

## [2.43.0](https://github.com/chodeus/chub/compare/v2.42.0...v2.43.0) (2026-07-27)


### Features

* align poster/asset apply pipeline on a strict Plex|Kometa apply_method ([6648d4e](https://github.com/chodeus/chub/commit/6648d4e8f2a131b05dd05ebc083b7bc671ac1881))
* **api:** cached Plex library catalog endpoint ([837cb95](https://github.com/chodeus/chub/commit/837cb95f6feda1a5c4c59921f1e068d05408640a))
* **api:** kometa-assets-scan endpoint + stale toggles in cleanup job ([4e3f2d9](https://github.com/chodeus/chub/commit/4e3f2d95d86d685874847b5c1d3b4867015d783a))
* **asset-renamerr:** two-column config settings page ([8a1d745](https://github.com/chodeus/chub/commit/8a1d7459cd2d9b54a2fea8e03378fdc979c65b44))
* **assets-search:** cache-coverage stats strip from the mock ([c2523ff](https://github.com/chodeus/chub/commit/c2523ffee05e7f463137ec7131915a9015097e85))
* **assets:** index all local assets in Assets Search via search-only rows ([6858ea6](https://github.com/chodeus/chub/commit/6858ea6c88caadb2abc8df855ab5a281de787045))
* **assets:** library-size stat + fix last-sync parsing (YYYYMMDD) ([64f5f01](https://github.com/chodeus/chub/commit/64f5f017232f775172c370a31759dd6a22475c8b))
* **asset:** source logos + backgrounds from fanart.tv ([93e1e5c](https://github.com/chodeus/chub/commit/93e1e5cc63ea02a1e1db081a38d3648ef49ae24f))
* **assets:** sortable unmatched tables + additional-artwork asset search ([ad5f407](https://github.com/chodeus/chub/commit/ad5f407b19a88fac003933c12d6cb576a5ee7559))
* **assets:** wildcard (*) title search in Assets Search ([05bbc88](https://github.com/chodeus/chub/commit/05bbc885cb177340cf78d526ed03cf0bbd747fb0))
* **auth:** short-lived scoped stream tokens for image/SSE URLs ([b0d48bc](https://github.com/chodeus/chub/commit/b0d48bc354f40092ec36bb5f131b54c6b0924b86))
* **border_replacerr:** surface per-poster failures in the summary (N21) ([c5db2e5](https://github.com/chodeus/chub/commit/c5db2e5eb301a69daf165da9e6e372c145e37cc4))
* **border:** full-library re-border on poster_renamerr run ([#231](https://github.com/chodeus/chub/issues/231)) ([a7211bb](https://github.com/chodeus/chub/commit/a7211bb2a8334d456e9139214627bcc7e214b043))
* **cleanarr:** add ID matching + ignore list to orphan asset cleanup ([152f7f2](https://github.com/chodeus/chub/commit/152f7f25bde013a201c2f5830595661292be56c8))
* **cleanarr:** restyle Poster Cleanarr config to the 3-pass mock ([0818c02](https://github.com/chodeus/chub/commit/0818c0221f7aa2882049bc0cf82c078253aff205))
* **config:** add PlexScope model + plex_scope split with legacy coercion ([8772165](https://github.com/chodeus/chub/commit/8772165b20b56de5493022a37537c8efb4f70718))
* **config:** add poster_cleanarr stale_duplicates settings ([d16d4be](https://github.com/chodeus/chub/commit/d16d4be8c6ad64343a0850461f18e459a8246385))
* **config:** migrator splits module instances into instances + plex_scope ([3b757b4](https://github.com/chodeus/chub/commit/3b757b4d50d7691b6427eb69564d212d795a0df7))
* **config:** reveal saved secrets on demand via the eye toggle ([788caf4](https://github.com/chodeus/chub/commit/788caf44f9b2379b01811212f262b19f38243767))
* **connector:** consume plex_scope + match_collections for media/collections ([c90862d](https://github.com/chodeus/chub/commit/c90862dad97da23a1d05ae53cbe1965c5262e471))
* **css:** migrate frontend from hand-rolled utilities to Tailwind v4 ([7b319e6](https://github.com/chodeus/chub/commit/7b319e661e8b8bd0e7ec9dd37f530ce9e3c05a68))
* **dashboard:** configurable module list and Health section on top ([bc76eae](https://github.com/chodeus/chub/commit/bc76eae085dcafa249ec6ef47b51490d72254c42))
* **dashboard:** configurable sections, refresh interval, and Up-next count ([b365650](https://github.com/chodeus/chub/commit/b365650b9a45433963078498d7f2e42a4b277a5c))
* **dashboard:** show per-instance sub-schedules on module status cards ([fd41e23](https://github.com/chodeus/chub/commit/fd41e23be21b1a1c946ed49a21852baf15f748dc))
* **extensions:** add stream_prefixes() hook for extension stream routes ([c99381a](https://github.com/chodeus/chub/commit/c99381afde3f69159587feb825c419dd3ba8763e))
* **extensions:** backend self-registration framework ([60d8149](https://github.com/chodeus/chub/commit/60d814938e2aca85cefc3704b2f33a993302a11b))
* **extensions:** frontend self-registration framework ([50a89b7](https://github.com/chodeus/chub/commit/50a89b7e7e94c4e8d4d94bc9a9b8f2759ca32a15))
* **extensions:** generic notification_formatters() hook for extension modules ([0683e84](https://github.com/chodeus/chub/commit/0683e849b8a29df46069cbb8ecf88917e787f257))
* **fields:** add generic action_button settings field type ([52e1658](https://github.com/chodeus/chub/commit/52e1658c7e22baf8079f82a5f04bb0bf761e33d0))
* **fields:** always-expanded card mode for array-object configs ([0871957](https://github.com/chodeus/chub/commit/0871957ad9459606203db41173fc42deba0a9f16))
* **fields:** contextual add-button label on array-object fields ([892197d](https://github.com/chodeus/chub/commit/892197d6bbe1d1d369324267f4df16d01706b9a9))
* **frontend:** add Orphaned assets section to Poster Cleanarr ([c9fa5d6](https://github.com/chodeus/chub/commit/c9fa5d6c70cd7ff5289101fcd48803368a82872a))
* **frontend:** add scanKometaAssets API client method ([58b35e4](https://github.com/chodeus/chub/commit/58b35e467f7ca19e910fe8c555f1e54e7808939a))
* **frontend:** clean-mode Bloat/Stale/Orphan checkboxes ([98c9bda](https://github.com/chodeus/chub/commit/98c9bda70c54b0cf6ad7e845941d145d1485ccff))
* **frontend:** numbered stale pill + pill legend on Poster Cleanarr ([3314e73](https://github.com/chodeus/chub/commit/3314e73070983f12ba6ec604e5dc981a1fa99099))
* **gdrive-presets:** add füsen CL2K drive ([14b446b](https://github.com/chodeus/chub/commit/14b446be666174e5d5c36935a356a81fadd83801))
* **gdrive-presets:** add füsen CL2K drive ([7085d78](https://github.com/chodeus/chub/commit/7085d78a4be9e72360077c3e3dc26c4149c256c2))
* **gdrive-presets:** add MajorGiant CL2K drive ([772eaee](https://github.com/chodeus/chub/commit/772eaeed262a6c38f66762aa7b9b192c3a9526e5))
* **gdrive:** bulk-add preset drives and configured sources ([db7d4d3](https://github.com/chodeus/chub/commit/db7d4d3f0aa82d44903b16e8f55b8af6bb1e4a1e))
* **gdrive:** confirm drive removal and optionally delete local folder + cache rows ([d9d4312](https://github.com/chodeus/chub/commit/d9d43125e739c1013c867a5fb08a3cedf061baaa))
* **gdrive:** use GDrive drives for poster matching by default ([e12f8ae](https://github.com/chodeus/chub/commit/e12f8aee1d07dd41fb35d95314c2c4342cbe6476))
* **instances:** opt-in gate for Plex libraries before they surface in CHUB ([cffcecb](https://github.com/chodeus/chub/commit/cffcecb8f1ec0074cbf392bd8fbf32614da3a664))
* **instances:** render *arr instance multi-select as pills ([1514b98](https://github.com/chodeus/chub/commit/1514b9882424446497a9e15620872361114e2eb7))
* **instances:** show live wanted/missing from *arr; drop poster match stats ([92bee9a](https://github.com/chodeus/chub/commit/92bee9a96ad32cdf922ed1842642c39b86aa6ab3))
* **instances:** show Plex snapshot freshness on instance cards ([00965e4](https://github.com/chodeus/chub/commit/00965e4e6bb87714ba7a27f3bd25a6c248b923f5))
* **instances:** support renaming an instance end to end ([71e9227](https://github.com/chodeus/chub/commit/71e92277af3447b85a6c4dfac8ea9334e86e991e))
* **jobs:** per-phase timing for orchestrated module runs ([624278c](https://github.com/chodeus/chub/commit/624278c48f57e2caa79ed5d5a7e730ac4a96be15))
* **jobs:** TRIGGER column + Clear&gt;30d to match mock ([91931a4](https://github.com/chodeus/chub/commit/91931a488ba48f758b0431b0fa688e5cfba1bf16))
* **labelarr:** bespoke mapping card with enabled toggle + label chips ([8bff174](https://github.com/chodeus/chub/commit/8bff17491263551661abbe734ca54b7f62914b74))
* **labelarr:** inline mapping CRUD with per-mapping enable toggle ([165e33b](https://github.com/chodeus/chub/commit/165e33bb3f51fe00903f9db8c23c88dc2ddbb8ef))
* **labelarr:** replace free-text library field with an opt-in picker ([a9de8a2](https://github.com/chodeus/chub/commit/a9de8a2ffbbd11abc4e315dad3cb72aaa74526a2))
* **layout:** remove the global breadcrumb bar ([37b5828](https://github.com/chodeus/chub/commit/37b5828faecee1751d60389f9f6b1b7767b08266))
* **library-manage:** restyle to the new mock ([c0eeeac](https://github.com/chodeus/chub/commit/c0eeeac9a41d858abf168d8e8a6abd907f2e9350))
* **library-stats:** report library health instead of poster matches ([dcf85cb](https://github.com/chodeus/chub/commit/dcf85cb25f2db589b505aad6014cda18f47c5d47))
* **login:** restyle to redesign mock ([e58ea21](https://github.com/chodeus/chub/commit/e58ea21d87cff89a1b15421f4a082a7046b0e833))
* **manage:** mock duplicate grid with lazy copies + bulk delete ([8ee3ce4](https://github.com/chodeus/chub/commit/8ee3ce47098634cd5e2940480b3f883a84c34765))
* **media-search:** surface external IDs, file name, and richer metadata ([9161778](https://github.com/chodeus/chub/commit/916177816ba67974fbb5ead5af4a7cfc1d4aa8d4))
* **module-configs:** lead with primary content, demote Log Level to Logging ([3f77fce](https://github.com/chodeus/chub/commit/3f77fcebdb1770cfa9e9b2aeff23a96301c5255d))
* **module-configs:** section Renameinatorr/Nohl/Health Checkarr/Jduparr/Plex Maintenance to mocks ([759ebec](https://github.com/chodeus/chub/commit/759ebec206d6b63d3152600cb72fe1018e155dba))
* **modules:** hub grid + per-module routes + hard-disable (Phase 1) ([354004e](https://github.com/chodeus/chub/commit/354004e624a27df415e9533c560d5db925d00d02))
* **modules:** migrate poster/asset/upload consumers to plex_scope ([63a078c](https://github.com/chodeus/chub/commit/63a078c8d20b948723f1cfa04fb4033957c073e8))
* **modules:** module-settings shell + boolean toggle rows (Phase 2) ([22e9e1a](https://github.com/chodeus/chub/commit/22e9e1a0b8fc55b7529d1e98fb9f28a6c18c2a1f))
* **nestarr:** surface path_mapping as expanded cards ([96118ac](https://github.com/chodeus/chub/commit/96118acbe0d563988cfc8964f8fecf86abd695a8))
* **notifications:** apply one webhook to multiple modules ([ba38fdd](https://github.com/chodeus/chub/commit/ba38fdd34c675cbeb1f57b6f202ff2ae76f40d74))
* **notifications:** per-destination model, migration, dispatch + redesigned page ([f3e6722](https://github.com/chodeus/chub/commit/f3e6722b9117d05b3586cffb14c52c1be6b24443))
* **notifications:** reshape Notifications to mock channel rows ([f632e34](https://github.com/chodeus/chub/commit/f632e34a6b327378cd79c4efcb02d3573e7d6286))
* **plex-maintenance:** two-column config settings page ([842faf5](https://github.com/chodeus/chub/commit/842faf5809fc4ec6f273c7e5587c0b6e8cd7078e))
* **plex-scope:** add-posters / match-collections as toggle rows ([51829eb](https://github.com/chodeus/chub/commit/51829eb7584239e134daca544a3078900afd4581))
* **poster_cleanarr:** separate orphan-asset cleanup from bloat settings ([a24606e](https://github.com/chodeus/chub/commit/a24606e91522ecf82a91a9df295a530cf84b2ee1))
* **poster-cleanarr:** add VALID_STALE_MODES constant ([675b8a9](https://github.com/chodeus/chub/commit/675b8a980f810fd905c3c284fbaf018a812135aa))
* **poster-cleanarr:** build canonical-folder map for stale detection ([a39d65c](https://github.com/chodeus/chub/commit/a39d65cc25fc81b3b81d925662c6dd67eb199e9b))
* **poster-cleanarr:** execute stale-duplicate report/move/remove safely ([5114aa6](https://github.com/chodeus/chub/commit/5114aa6d0514db376b701b7d6313587c7a8249b5))
* **poster-cleanarr:** library opt-out, hide music "(unknown)" clutter, clearer asset-pass settings ([ecf0ab5](https://github.com/chodeus/chub/commit/ecf0ab5cef83c5936bb4a391a7f1d3dd1f20efe3))
* **poster-cleanarr:** orchestrate stale-duplicate pass + run() wiring ([e49735d](https://github.com/chodeus/chub/commit/e49735dadbf19f509428f1cf4f8a3c4ea5cf58c8))
* **poster-cleanarr:** prune dead symlinks in the orphan pass ([56c3792](https://github.com/chodeus/chub/commit/56c379225f34331fcf8c807636ebe054105107c2))
* **poster-cleanarr:** scan for stale-duplicate asset folders ([7c030a8](https://github.com/chodeus/chub/commit/7c030a8d9ea709bf6105e5df5a5b057d66b65ffc))
* **poster-cleanarr:** show section-toggle descriptions, split the bloat-pass settings ([381377c](https://github.com/chodeus/chub/commit/381377cd19b86578b6b53faf1e0f092d2634da4d))
* **poster-cleanarr:** surface stale-duplicate stats in report + notification ([6a9a52c](https://github.com/chodeus/chub/commit/6a9a52c9bc8fabc31889b81f6f80babe3f72fcec))
* **poster-cleanarr:** two-column config page with pass cards and help tooltips ([29bc755](https://github.com/chodeus/chub/commit/29bc755ef8da158bfa27bdf55dd1530e8308d6b8))
* **poster-renamerr:** priority badges + bottom-wins hint on source dirs ([4786afe](https://github.com/chodeus/chub/commit/4786afedce81fbbe4e4d2cb2ee0488448c9fa15f))
* **poster-renamerr:** reorder config to mock (Output → Source → Targets → Chained actions) ([73b3eab](https://github.com/chodeus/chub/commit/73b3eabf648ce6376d9b569b00de3ac9342551bf))
* **poster-renamerr:** two-column config settings page ([e386781](https://github.com/chodeus/chub/commit/e386781e3ca4178bed55cf6c9c7a6daddcbd7cfe))
* **poster-stats:** adopt mock layout + Top contributors ([25905fe](https://github.com/chodeus/chub/commit/25905febd3e2d2ab50e21b4d775f5f27a1e9e8db))
* **posters:** manual artwork picker for logo/background/squareart ([2c7fb8b](https://github.com/chodeus/chub/commit/2c7fb8b804d4016a18ff6e22806b2d041f04e673))
* **posters:** per-library uploads + skip tracking, unlock manual matches ([0da4204](https://github.com/chodeus/chub/commit/0da4204a153b3479b261da1244eff1f6b3bdaa1a))
* **posters:** unified, readable CL2K/MM2K provenance stamp ([9b7a0e1](https://github.com/chodeus/chub/commit/9b7a0e1aec8c0a13435b91ef097954cbf15caef1))
* **posters:** warn on year mismatch for ID-matched uploads ([77fa650](https://github.com/chodeus/chub/commit/77fa650daba3b0b25ba0814790a1fe07052d12e6))
* **renameinatorr:** add refresh-before-rename; fix inert ignore tag ([2fc3dc2](https://github.com/chodeus/chub/commit/2fc3dc2996189f2e197956de7909c0e40b06b356))
* **schedule:** drop stats strip, add base/profile/block legend ([f53e613](https://github.com/chodeus/chub/commit/f53e613555f601aa2362efd6cdb4bb13a8e9e340))
* **schedule:** remove the per-module Test button ([a419272](https://github.com/chodeus/chub/commit/a41927234b9569a3e33174ce0b7cb082a3fd50db))
* **schedule:** surface Upgradinatorr per-instance sub-schedules in UI ([b17ce5d](https://github.com/chodeus/chub/commit/b17ce5d504c7acfa61e73d4e3f7a994306558de1))
* **search:** accept colon id tags and bare numeric ids in search queries ([642684c](https://github.com/chodeus/chub/commit/642684c3c54a736cc77b030d18f0d2030d7cfab3))
* **search:** colon id tags, bare numeric ids, and a search-syntax hint ([9b74e94](https://github.com/chodeus/chub/commit/9b74e94278f43c10de46847b95edaaaad205aa29))
* **search:** id search by colon tags and bare numeric ids in Assets Search ([f2de844](https://github.com/chodeus/chub/commit/f2de844e0dbe338817c565f262c5ed71688a874c))
* **search:** match tmdb/tvdb/imdb id in asset and library search ([5c3406a](https://github.com/chodeus/chub/commit/5c3406a0079a94b123925b9c37de40727742c4a5))
* **settings:** accent picker + Appearance section on General ([3212207](https://github.com/chodeus/chub/commit/32122072bc459f3922f06998520dafef87830bfc))
* **settings:** add poster_cleanarr stale-duplicate settings ([1ad121e](https://github.com/chodeus/chub/commit/1ad121ed20c70efea1259d71121837c64e0d33ea))
* **settings:** drop the Settings cards hub; re-run wizard from General ([3e7087a](https://github.com/chodeus/chub/commit/3e7087a3b9f8307447abc7da7a42588d812bfcf0))
* **settings:** extension-aware Modules hub + Schedule, add runnable:false flag ([1e4f9d8](https://github.com/chodeus/chub/commit/1e4f9d81613ce11324417ff5b35da3c82f6b7bbe))
* **settings:** extension-aware Notifications + Dashboard; share config-only helper ([d0133c2](https://github.com/chodeus/chub/commit/d0133c230c9235e9477dbd0e63049a30cfcf8b45))
* **settings:** generic 'requires' precondition warning on module config pages ([b2eccb6](https://github.com/chodeus/chub/commit/b2eccb697933f9b5b5299b5ec0e8128e6dfe3510))
* **settings:** label-left/control-right field rows (Phase 2b) ([058a2db](https://github.com/chodeus/chub/commit/058a2db0388020240590f1f1067eb7ae0f0acf2e))
* **settings:** segmented field type for either/or enums ([aa497fc](https://github.com/chodeus/chub/commit/aa497fcdae723cec9f53338f098d918c33444202))
* **setup:** first-run setup wizard with a config-aware gate ([34d6e11](https://github.com/chodeus/chub/commit/34d6e11d207337425388719a2a81171330a57995))
* **stats:** count Sonarr at the episode level (shows/seasons as context) ([da67e1e](https://github.com/chodeus/chub/commit/da67e1ef9c97273d0b1cf6426fd5a4cb51a4cd7f))
* **stats:** order Artist above Album in By type ([24d75e5](https://github.com/chodeus/chub/commit/24d75e532d51b0c788002d7a8fb8baeb17ef4290))
* **stats:** pair By type with By instance, consistent card borders ([08396a4](https://github.com/chodeus/chub/commit/08396a409792868093c03b633e3d6e88d03477eb))
* **stats:** regroup Library Statistics by synced instance ([4c5ecc1](https://github.com/chodeus/chub/commit/4c5ecc18992bb02af0a07036d0b3808d7502c284))
* **stats:** show Sonarr Series AND Episodes as separate cards ([c7b7f3c](https://github.com/chodeus/chub/commit/c7b7f3cde9e240055a020059a0728e00e3403ab4))
* **sync-gdrive:** bespoke drive table matching the mock ([8311d97](https://github.com/chodeus/chub/commit/8311d97a200ab8009d3de0e6ee1762f59d66ec7d))
* **sync-gdrive:** section config to mock (Authentication → Options) ([8070571](https://github.com/chodeus/chub/commit/807057124e22eaab9d8bc41a503890b6207d0714))
* **sync:** background instance reconciliation from the Instances page ([5d8fed9](https://github.com/chodeus/chub/commit/5d8fed9b2f78573e85b461e4a7c614dfe346d07a))
* **sync:** per-instance sync-completion timestamp for accurate freshness ([72b36c9](https://github.com/chodeus/chub/commit/72b36c98e89720a242e6a67bb880fce8c3262225))
* **sync:** restrict gdrive sync to image types and cap file size ([c009fef](https://github.com/chodeus/chub/commit/c009fef93fad51d1761dc85511705a877627233e))
* **system:** rebuild System settings to redesign mock ([924bdd6](https://github.com/chodeus/chub/commit/924bdd6df7da051332f88232b1df09cc80d9d1c6))
* **tmdb:** add circuit breaker to abort runs on sustained TMDB outage ([4eeaf6a](https://github.com/chodeus/chub/commit/4eeaf6ab2326c290dbed5401a6f4b06f451a80f9))
* **ui:** add the mock's filter ⌘F hint to the Logs search input ([610f25d](https://github.com/chodeus/chub/commit/610f25d6a9ad32c177d55931b8fe0094ea242cce))
* **ui:** explicit Libraries catalog section on Plex instance card ([90da298](https://github.com/chodeus/chub/commit/90da298b6b7a54f71921cc46751aea44d4ec257b))
* **ui:** plex_scope field (catalog picker + match_collections) ([605aa6a](https://github.com/chodeus/chub/commit/605aa6acceec127c7fbb9d449b1d95ca0d61beb8))
* **ui:** polish Settings sub-components to match mocks ([6852da3](https://github.com/chodeus/chub/commit/6852da3a81f713508e2f69e5c976edefc5122433))
* **ui:** redesign Assets Search ([14c7deb](https://github.com/chodeus/chub/commit/14c7debb0b8b627f5e3ebdb1584589a6425f66aa))
* **ui:** redesign Border Replacerr + Logs ([1cfdb2c](https://github.com/chodeus/chub/commit/1cfdb2c435e83926167c5f196ad7bf9ce1234f45))
* **ui:** redesign dashboard as a dense ops board ([0652426](https://github.com/chodeus/chub/commit/06524264c9e154aac6648bf9bfc97d65c83510cd))
* **ui:** redesign foundation — fonts, palette tokens, sidebar shell ([6be1997](https://github.com/chodeus/chub/commit/6be19979c3da3aa6fa08a6d5700f72680120c828))
* **ui:** redesign GDrive Sources + Poster Statistics ([93db848](https://github.com/chodeus/chub/commit/93db84845f09bb1bd96055a7124fa9cd50874d60))
* **ui:** redesign Library section (search, manage, stats, label sync) ([cc6dcfa](https://github.com/chodeus/chub/commit/cc6dcfa30261738aa193f278585db8e79e01c733))
* **ui:** redesign Poster Cleanarr + Unmatched Assets (master-detail) ([d339195](https://github.com/chodeus/chub/commit/d339195b46f6214a7a219415f4bfefe03e994ca9))
* **ui:** redesign Settings Jobs — mono stat strip + filter pills ([38a22d8](https://github.com/chodeus/chub/commit/38a22d8ef6146ae2e1f2a507f043c6f0d28b4323))
* **ui:** redesign Settings page shells (Instances/General/Modules/Notifications/Schedule) ([e0120f8](https://github.com/chodeus/chub/commit/e0120f8db661d0ce79431e407200c90397d281cb))
* **ui:** redesign Settings shell — dense PageHeader + hub/System/Webhooks ([bc5a2e9](https://github.com/chodeus/chub/commit/bc5a2e987848de79d08c6114da844bca56af6f79))
* **ui:** remove Quick start section from the dashboard ([c28978e](https://github.com/chodeus/chub/commit/c28978e5874d18bf161571c1a72aa284cc63bd86))
* **ui:** retire desktop top header; tighten Logs to match mock ([03a9910](https://github.com/chodeus/chub/commit/03a9910be5a96c8cc6662e4acc48f7d491dc3d4e))
* **ui:** split instances/plex_scope in poster/asset/unmatched schema ([eb371de](https://github.com/chodeus/chub/commit/eb371de85a95af7c67b97c190fb78c2d760bd996))
* **unmatched:** add additional-artwork reset + load count on mount ([fa406cd](https://github.com/chodeus/chub/commit/fa406cd715567ca73a9d7c8636af9043b0026c05))
* **unmatched:** add Additional-artwork view alongside posters ([4c73b3f](https://github.com/chodeus/chub/commit/4c73b3fd2581570271f27173c55381e9d411c284))
* **unmatched:** add poster-match reset to the Unmatched page ([ed61339](https://github.com/chodeus/chub/commit/ed61339579356e6880491358433ccc5b50b17509))
* **unmatched:** drop blank thumb; add CL2K build action to artwork rows ([2cea2da](https://github.com/chodeus/chub/commit/2cea2da002732b2ad0ca2e38dc6e1352ca13573f))
* **unmatched:** make additional-artwork coverage provenance-based ([9efaf11](https://github.com/chodeus/chub/commit/9efaf11ba63590f25e16f7e4692f90bc0028e498))
* **unmatched:** match Additional-artwork view to the poster styling ([fab3be8](https://github.com/chodeus/chub/commit/fab3be8a8db5c1c5b7c6266fcae5b30fae8e2d29))
* **unmatched:** per-media artwork table + pagination + clickable type cards ([af1aac2](https://github.com/chodeus/chub/commit/af1aac2a38b48d2f81d51e0a1513d74bd73d4cd1))
* **unmatched:** read plex_scope for instance/library filtering ([47467f7](https://github.com/chodeus/chub/commit/47467f70e0721672e239c484e201002bc6ac6860))
* **unmatched:** reshape unmatched list to redesign mock ([66bae91](https://github.com/chodeus/chub/commit/66bae9169a63b34dec840983e2b5f75edb49a6a4))
* **upgradinatorr:** bespoke profile card matching the mock ([ff67a79](https://github.com/chodeus/chub/commit/ff67a796aa4722e75f97218a2a63bc45f9a3d3b1))
* **webhooks:** auto-detect the provisioning base URL + fix precedence ([7ed6572](https://github.com/chodeus/chub/commit/7ed65727dccd00eae8acf494723da5cfee28de82))
* **webhooks:** banner when ingest endpoints are unauthenticated ([68c5acd](https://github.com/chodeus/chub/commit/68c5acd3eab621e4c9b28d83778d0ebf9d2f8a57))
* **webhooks:** honor X-Forwarded-For from trusted proxies for instance matching ([e3d9833](https://github.com/chodeus/chub/commit/e3d98336631c21b6df450110f3f4a088e140816d))
* **webhooks:** payload-first routing + auto-provision poster webhook into *arrs ([cafc4f1](https://github.com/chodeus/chub/commit/cafc4f1aa608c73554c382b5929d1117f6b70436))
* **webhooks:** reshape Webhooks page to mock + per-origin telemetry ([465febf](https://github.com/chodeus/chub/commit/465febfedca64536032b9e89b2e2881ed249cf25))


### Bug Fixes

* **accent:** use text-on-color (not hard-coded white) on brand surfaces ([bda9875](https://github.com/chodeus/chub/commit/bda98755b2d7bcd407e04a29723069c1f1d74c12))
* **api:** include plex_scope instances in module test endpoint ([fd38bbe](https://github.com/chodeus/chub/commit/fd38bbe0461ba6c615e494aa968e9cb7e76a3d96))
* **api:** SSRF-guard Plex library fetch (single + catalog endpoints) ([0670584](https://github.com/chodeus/chub/commit/0670584bebb7b9e1aa705e269a37cc823afe66f3))
* **asset_renamerr:** dry-run must not persist match state or log as applied ([95b8bcd](https://github.com/chodeus/chub/commit/95b8bcd3990df52a4a7ba0f2e52fc486600f01c0))
* **asset_renamerr:** per-library backfill for direct asset apply (P7, WS-4) ([2182f25](https://github.com/chodeus/chub/commit/2182f25b732a4509165156abc103f873f54f518b))
* **asset_renamerr:** skip release-unready items on the Plex apply path ([c360758](https://github.com/chodeus/chub/commit/c36075820c75c1ad86b33b9ecabe68bcf0903fe2))
* **asset,border:** clear CodeQL alerts (dead code + empty-except comment) ([6c6215b](https://github.com/chodeus/chub/commit/6c6215b373830b38d1962bf92bd071e374b12399))
* **asset:** fanart is Plex-only (stream, never download); Kometa = g-drive only ([e445ac0](https://github.com/chodeus/chub/commit/e445ac0cdfb5d4b81d1de131c2aa44611d9b5dd8))
* **assets:** list all owners/styles regardless of the Image filter ([fa6565b](https://github.com/chodeus/chub/commit/fa6565b307ba94193d7ab202cfb2e7cc0392c8d4))
* **assets:** render additional artwork with object-contain on a transparency backdrop ([7d0ba43](https://github.com/chodeus/chub/commit/7d0ba43fa6a545c40cc91f21d7e0e106c5637e5c))
* **assets:** stop expecting clear logos on seasons ([e211839](https://github.com/chodeus/chub/commit/e211839cf4feea9a2ce7007083aefc091b32f2a0))
* **auth:** keep the stream token warm + rebuild image URLs when it lands ([f128393](https://github.com/chodeus/chub/commit/f1283936020b9dc97e37f0d062b3af1414359ca9))
* **auth:** log request path on unauthorized 401s ([b160c6b](https://github.com/chodeus/chub/commit/b160c6b503a26c6c1588937692f28c5dd70831f9))
* **auth:** render posters via token-less URLs when auth is not configured ([0ac553c](https://github.com/chodeus/chub/commit/0ac553c31591ce7747d4ebfa44c5d5a8d8224f92))
* backend correctness and reliability fixes ([d07559a](https://github.com/chodeus/chub/commit/d07559a12a8a45e8ab30d7134b95e8ebe7f08ed3))
* **badge:** stop dev prop-validation false-positives ([bf86c51](https://github.com/chodeus/chub/commit/bf86c517067db44a40b1fe39dfe8ef681f22847e))
* **border_replacerr:** crash-proof holiday parsing + bounds + anchors (WS-3) ([091107b](https://github.com/chodeus/chub/commit/091107b25f6d95fb37315a242a490f67b4a07fb3))
* close audit backlog — redaction gaps, atomic ops, SSRF guard, logging polish ([856168f](https://github.com/chodeus/chub/commit/856168fd38aad90982ec54d9d60518ea7f2e878a))
* **concurrency:** harden parallel runs + fix correctness bugs from today's audit ([cff5a5d](https://github.com/chodeus/chub/commit/cff5a5d13c8e0c5cdb6ec6ee64c79dbd627e076d))
* **config:** dedup/idempotency + ambiguous-name safety in plex_scope relocation ([1c88165](https://github.com/chodeus/chub/commit/1c88165fe47ccec7ccb604fa5fd776cf56f690fb))
* **config:** reject invalid action_type/apply_method/count (WS-8) ([87ef49f](https://github.com/chodeus/chub/commit/87ef49f9ff8da1f50167c7c53ff61518fce3a7a1))
* **config:** relocate bare Plex-name strings in instances into plex_scope ([b93944d](https://github.com/chodeus/chub/commit/b93944df0a22f4dcef2b9a7cba3dead7b6144e21))
* **config:** split a shared-webhook notification destination by event ([0bf4339](https://github.com/chodeus/chub/commit/0bf4339f10e454f779824b70f98e4280aad6a07b))
* **config:** stop migrator flattening supported unmatched_assets Plex scope ([4fb6ca5](https://github.com/chodeus/chub/commit/4fb6ca5393a666ea9a22553f5f0fc089ce5e13c9))
* **css:** restore utilities and colour aliases dropped by the Tailwind migration ([82f5433](https://github.com/chodeus/chub/commit/82f5433fdc235f16f5a8bb6ea86727498513c351))
* **data-loss:** guard destructive poster/nohl/upload paths ([63d73b5](https://github.com/chodeus/chub/commit/63d73b5ea6e7bf4df271073c809c927e7ee31edc))
* **db:** DB robustness — busy_timeout, rebuild lock, safe ALTER (WS-5) ([ea735cd](https://github.com/chodeus/chub/commit/ea735cda8a76f8069ace1d64cb780906a58fca20))
* **deps:** drop dead stylelint plugin, time-box the brace-expansion advisory ([#402](https://github.com/chodeus/chub/issues/402)) ([560a102](https://github.com/chodeus/chub/commit/560a10283e830109917fe4692f7876ecf38d2e85))
* **deps:** migrate to react-router 8 to clear GHSA-qwww-vcr4-c8h2 ([#394](https://github.com/chodeus/chub/issues/394)) ([3b943a5](https://github.com/chodeus/chub/commit/3b943a5a83ef6b45a8050b5c2f6b892b43fbd870))
* **deps:** pin Pygments 2.20.0 (unpinned transitive of shipped pytest) ([5980aa7](https://github.com/chodeus/chub/commit/5980aa7ca4344045841325a1271846bd71476977))
* **deps:** update all non-major dependencies ([#225](https://github.com/chodeus/chub/issues/225)) ([ada2ff5](https://github.com/chodeus/chub/commit/ada2ff5d922f234776d908b5b9b67eabea6c9ce6))
* **deps:** update all non-major dependencies ([#227](https://github.com/chodeus/chub/issues/227)) ([ebb8e24](https://github.com/chodeus/chub/commit/ebb8e2424509fc397547f40faea3da438cc6d90c))
* **deps:** update all non-major dependencies ([#251](https://github.com/chodeus/chub/issues/251)) ([5bb7b32](https://github.com/chodeus/chub/commit/5bb7b32bf4dedc6a581ec16b1168969fe4dea2bc))
* **deps:** update all non-major dependencies ([#254](https://github.com/chodeus/chub/issues/254)) ([db5837c](https://github.com/chodeus/chub/commit/db5837cb0d7b5f301e1cfe33ac1ae6240701b091))
* **deps:** update all non-major dependencies ([#274](https://github.com/chodeus/chub/issues/274)) ([27947e8](https://github.com/chodeus/chub/commit/27947e8a56979f71cd83550f6d42ee783d38e31e))
* **deps:** update all non-major dependencies ([#275](https://github.com/chodeus/chub/issues/275)) ([75e59fe](https://github.com/chodeus/chub/commit/75e59fee769a5dee53941f2e3124fc4a808363f1))
* **deps:** update all non-major dependencies ([#335](https://github.com/chodeus/chub/issues/335)) ([b0b758f](https://github.com/chodeus/chub/commit/b0b758f20de234f7863d3265dafa51a299691ef6))
* **deps:** update all non-major dependencies ([#342](https://github.com/chodeus/chub/issues/342)) ([30b120b](https://github.com/chodeus/chub/commit/30b120bfdf2d544f28353633216ac80a70b32799))
* **deps:** update all non-major dependencies ([#376](https://github.com/chodeus/chub/issues/376)) ([fe33536](https://github.com/chodeus/chub/commit/fe33536950c59f62d7b6e1f9ca1fb1bf5fbb428b))
* **dirlist:** compact flat path rows to match the module mocks ([6d06753](https://github.com/chodeus/chub/commit/6d06753db016eb832b194899bc0d243079c97564))
* **docker:** download rclone to its checksummed filename so sha256sum -c passes ([73575b3](https://github.com/chodeus/chub/commit/73575b3365bbad55fcc9156830767f839130c55c))
* **docker:** install Node from the official image, not NodeSource ([#400](https://github.com/chodeus/chub/issues/400)) ([d2afe5d](https://github.com/chodeus/chub/commit/d2afe5d1baddc23f2526223765d2026db97bb613))
* **fields:** action_button ignores a stale result after its row changes ([07accbe](https://github.com/chodeus/chub/commit/07accbe0873c3a14e231f63be4fdcd1345fd4e5e))
* **fields:** stop leaking non-DOM props onto field elements ([2c8ab9e](https://github.com/chodeus/chub/commit/2c8ab9e8c0a40e31276c3c80b352f0a73816dd18))
* **frontend:** cache invalidation, callbacks, and falsy-value bugs ([4b1988b](https://github.com/chodeus/chub/commit/4b1988b8356e66ea4bc6179b2982080e7ff6d1ec))
* **frontend:** FloatField 0-value, duplicates-resolve cache, instance keys ([b91ad0a](https://github.com/chodeus/chub/commit/b91ad0a14fbc0003b6b3355a476bb20c43b30ad3))
* **frontend:** guard stale-data races in useApiData + JobsPage (P31, N28) ([4d48ab9](https://github.com/chodeus/chub/commit/4d48ab933df3da416f4752f9f797ec46fc3cd99e))
* **gdrive-table:** flat fields in inset rows to match the mock ([483bb44](https://github.com/chodeus/chub/commit/483bb44ce0c9ef96f0a25c7e942cc56724517814))
* harden restore/lookups/tags, add plex-maintenance dry-run + paging ([90cdc1f](https://github.com/chodeus/chub/commit/90cdc1fbec15b8898143dc90ae650c4b26aa9157))
* **health:** report DB status via worker so /api/health isn't falsely degraded ([ad5fc3d](https://github.com/chodeus/chub/commit/ad5fc3da6ef582f3486feab879128725ff096ee2))
* **instances:** case-insensitive source on rename + composite UI-state keys ([cf47a9f](https://github.com/chodeus/chub/commit/cf47a9fcaa78d360c57e0276ec6f7794cc152335))
* **instances:** disable redirects on SSRF-validated health/test probes ([3275286](https://github.com/chodeus/chub/commit/32752869ec1ba97d9375ce8e4f8c756c1a6f66da))
* **instances:** don't clobber stored API key with the redacted placeholder ([b4c7712](https://github.com/chodeus/chub/commit/b4c77124deb19b9a02e0492b4a542f0e0a7eccf9))
* **instances:** read sync_schedule from the nested section response ([dad875c](https://github.com/chodeus/chub/commit/dad875c172f8eafdc97560c066a57a380c3fbc0d))
* **instances:** resolve redacted API key by URL when renaming ([92818aa](https://github.com/chodeus/chub/commit/92818aa9647d4ad793582ca30bde253f77661cc8))
* **jduparr:** use jdupes --json scan, honest link count, and harden run loop ([a0e7e29](https://github.com/chodeus/chub/commit/a0e7e29677e9f355e6b43079aa09b4d199f5d168))
* **jobs+modules:** mock-style job actions; drop module-config breadcrumb ([f71a72f](https://github.com/chodeus/chub/commit/f71a72f59acc1ce1290c5f72a5c3bf628f60ce69))
* **jobs:** collapse a composite trigger to its readable base ([d8d0942](https://github.com/chodeus/chub/commit/d8d0942861b551c44a009c55d626305eda75f319))
* **jobs:** humanize the job-type label ([bcf14f0](https://github.com/chodeus/chub/commit/bcf14f005c48cea2ef9920e9e5339cf0b5964455))
* LIKE escaping, optimize clobber-guard, transient-cache, 0-is-falsy, logout cache, CI perms ([b2724e5](https://github.com/chodeus/chub/commit/b2724e5d798b744f75d6dd5a0ccfadbebbc529cf))
* **logger:** attach module file handler regardless of root handlers ([b0911d9](https://github.com/chodeus/chub/commit/b0911d9463216db42ddf67b511e3fbbc2dbb2fc8))
* **logger:** redact secrets in tracebacks, yaml OAuth tokens, and the Notifiarr key ([329c9ff](https://github.com/chodeus/chub/commit/329c9ffe05639153ea39c5ce062ad5b7eeb43817))
* **logs:** don't list stale on-disk dirs as log modules ([43cb87e](https://github.com/chodeus/chub/commit/43cb87ee1ef8ec27fc845c33ef19c7b7416a414a))
* **logs:** keep container stdout ordered and free of TTY/raw-stdout noise ([305fb52](https://github.com/chodeus/chub/commit/305fb5294310ca56a4530104ee068ab22d57c37f))
* **logs:** list config-only extension modules (e.g. cl2k_maker) ([9e4c810](https://github.com/chodeus/chub/commit/9e4c8102bf23a8c31b7ffbaa7be653a941214b35))
* **logs:** stop double-encoding &lt; and &gt; in the log viewer ([d813957](https://github.com/chodeus/chub/commit/d813957a06ac769922dc57a297bab32aff7c4eb5))
* **matching:** strip *arr "(0)" unknown-year placeholder in normalization ([7d43953](https://github.com/chodeus/chub/commit/7d43953f1abf4be0fb1b9e36aa3efa0979f25980))
* **match:** season-poster GUID matching + collection attrs (WS-4 part 1) ([6224ded](https://github.com/chodeus/chub/commit/6224ded46f2d45903d1c4bb905c5f81ee78e10d2))
* **mobile:** stat strips wrap instead of overlapping on narrow screens ([01c9b8b](https://github.com/chodeus/chub/commit/01c9b8b94e0c9131c5a7f1322697ec55c35eef71))
* **modules:** redact secrets in GET /api/modules/{name} ([34beb40](https://github.com/chodeus/chub/commit/34beb40b0f6740cfa42391c96db387e324b1750b))
* **nestarr:** make ARR↔Plex unmatched detection opt-in ([d86f31c](https://github.com/chodeus/chub/commit/d86f31cc266a41371581303958b54209bfe17c2d))
* **nestarr:** reduce unmatched-assets false positives ([7b690dd](https://github.com/chodeus/chub/commit/7b690dd4d9f70497caea5cbeec5a0cbcbb37adb5))
* **nohl:** label summary counts as non-hardlinked, not "scanned" ([8e4f26f](https://github.com/chodeus/chub/commit/8e4f26f14a877ccbbff8b4f150e9b8e6f1a4aa89))
* **notifications:** honor Discord retry_after and summarize huge runs ([9a75c7a](https://github.com/chodeus/chub/commit/9a75c7ae93b5cbf12385a68ae81d292d17353cbb))
* **notifications:** redact webhook URLs and align schema to backend ([51a5e0a](https://github.com/chodeus/chub/commit/51a5e0a5c2da1d347ff09946f581f9d216d2eab3))
* **notify:** stop redacted placeholder clobbering destination webhooks ([81072c9](https://github.com/chodeus/chub/commit/81072c9fbdf9df46e4447df8ff46881fdf6e7a42))
* orphan pass spares Kometa asset files; asset_renamerr reports progress ([c9f082d](https://github.com/chodeus/chub/commit/c9f082d3b8ce9e504262d544ae1a9b920888c8d0))
* **plex_metadata:** don't cache a bloat scan when the Plex DB copy failed ([2c1f2d5](https://github.com/chodeus/chub/commit/2c1f2d588bc0c255b4c0c7b568728fe9e112c176))
* **plex:** resolve upload targets by ratingKey, not *arr title ([c3e96e3](https://github.com/chodeus/chub/commit/c3e96e3de605fa5d0a3d72db8d3bff996bd78e95))
* **plex:** scope the snapshot TTL guard per-library so labelarr keeps the reuse optimization ([4b5f8c4](https://github.com/chodeus/chub/commit/4b5f8c4d413fc27edea9476487e0c920618d33a3))
* **plex:** year-disambiguate title matches to prevent wrong-year uploads ([029ba19](https://github.com/chodeus/chub/commit/029ba192c38c07aa4c63a206d2dd48efeeda657d))
* **plex:** year-disambiguate title matches; log 401 request path ([87b5ab7](https://github.com/chodeus/chub/commit/87b5ab797837602d13ee451e2bcc33a9b5cc93be))
* **poster_cleanarr:** run metadata scans off the event loop via background jobs ([5b18c83](https://github.com/chodeus/chub/commit/5b18c8359bdebbebe9c0da0d3265ef0ba6d65f6b))
* **poster_renamerr:** library-aware plex skip-unchanged + lock the match phase ([284a5c9](https://github.com/chodeus/chub/commit/284a5c92bf851037ae66d6b3c17cb35c50bcb598))
* **poster_renamerr:** report only genuine Plex uploads and stop steady-state border churn ([#356](https://github.com/chodeus/chub/issues/356)) ([e24bd89](https://github.com/chodeus/chub/commit/e24bd89751d9f69f99226480938bf566d4d51c4c))
* **poster-cleanarr:** bound the panel to the viewport so the media list scrolls internally ([2d50652](https://github.com/chodeus/chub/commit/2d50652e929ff0fb5cf30bbea8864dc96bc5fc8c))
* **poster-cleanarr:** clarify detail bloat is selected-level scope ([0063423](https://github.com/chodeus/chub/commit/00634236b3d31925aae1a154ca0587755ac0f0bc))
* **poster-cleanarr:** mock-style checkboxes + variant status tags ([4bbc4e3](https://github.com/chodeus/chub/commit/4bbc4e39c562f264c599156128173f6d533c25f1))
* **poster-cleanarr:** page through all bundles so tabs show the whole library ([4ecb4a0](https://github.com/chodeus/chub/commit/4ecb4a011bc80d390401b2cba9b39d997f7e9e22))
* **poster-cleanarr:** show cached scan on return, don't re-scan ([aa54b4a](https://github.com/chodeus/chub/commit/aa54b4a03a05a341e025da83da5ea444b4d1caeb))
* **poster-renamerr:** atomic poster copy via temp + os.replace ([7238c2d](https://github.com/chodeus/chub/commit/7238c2d037712d1b4d5fc6ea47e81f033f2f7643))
* **poster-renamerr:** re-stage assets when a media folder is renamed ([43fed79](https://github.com/chodeus/chub/commit/43fed79e8b42d0d81ccd5055d44f456f20c09fd8))
* **poster-stats:** guard non-array detail data (page crash) ([a353e00](https://github.com/chodeus/chub/commit/a353e0099616850ee8bcf802a6d77d1b5f55a4cb))
* **posters:** delete the configured gdrive folder, not the request path ([a9766dc](https://github.com/chodeus/chub/commit/a9766dc74e4045ca839c17b1eec4c1633ffab3bd))
* **posters:** don't send Discord/Notifiarr alert for unconfigured plex_path ([55e9e81](https://github.com/chodeus/chub/commit/55e9e81510c905f575b0805c687d5bc2124fc6f6))
* **posters:** make Asset Search poster download actually save a file ([4cd6f72](https://github.com/chodeus/chub/commit/4cd6f72a23bb133ad4949354e624df738b370c15))
* **regex:** factor season delimiter prefix — clears CodeQL unmatchable-caret ([#183](https://github.com/chodeus/chub/issues/183)) ([c6630f4](https://github.com/chodeus/chub/commit/c6630f4a5de7eca539040092c4276ecbe5aea25c))
* **renameinatorr:** honour ignore tags across the tag-cycle reset ([01c6a49](https://github.com/chodeus/chub/commit/01c6a49ef3c7c6b53850374eb82f059eb7ddb4f6))
* **resilience:** ARR/worker/TMDB/Plex-wait robustness (WS-6) ([5f167b5](https://github.com/chodeus/chub/commit/5f167b5df8064f0aab5e30a0ec00506251bf9872))
* resolve CodeQL alerts (dead assignment, repeated imports) ([30145dd](https://github.com/chodeus/chub/commit/30145dd2928ed931726b259b09233bebafc48dee))
* **schedule:** reject malformed schedule strings at the API ([811c528](https://github.com/chodeus/chub/commit/811c528d7a8eb80b72c75d01ed4bf9cb687c5d94))
* **security:** close asset-apply path traversal + clear CodeQL test findings ([f7ae28b](https://github.com/chodeus/chub/commit/f7ae28b47efc91726fbd049c4e35ebe07049e877))
* **security:** close auth-boundary and secret-exposure gaps (WS-2) ([6681373](https://github.com/chodeus/chub/commit/6681373a931837049d4999813d4cae16711ff3bc))
* **security:** document intentional empty-except blocks to clear CodeQL notes ([fbd2d02](https://github.com/chodeus/chub/commit/fbd2d02fd15894b4eb563fd6f42ba2d9f80883f6))
* **security:** fail closed on config error + warn on unauthenticated webhook ingest ([cd8bd22](https://github.com/chodeus/chub/commit/cd8bd22799e54ae686979db420d10c221245c21f))
* **security:** fail-closed SSRF guard, key-exfil + redirect guards, auth-section write block ([dd405a0](https://github.com/chodeus/chub/commit/dd405a0b2f33b2903de2bdc964834e248689739d))
* **security:** harden CodeQL-flagged regex and fanart URL construction ([8f1e63f](https://github.com/chodeus/chub/commit/8f1e63f0039c4492a648b03f93b215704f06e9af))
* **security:** harden Plex XML parsing and break config import cycle ([d0cafe5](https://github.com/chodeus/chub/commit/d0cafe5e0d3bd4d9d1d629063e1cf4723965b7d0))
* **security:** stop world-chmod 777 of CONFIG_DIR; lock down secrets ([1c9d62f](https://github.com/chodeus/chub/commit/1c9d62f281e25da30422aaa7b46f8ef4c21e25d8))
* **settings:** add fanart.tv module card description ([12de181](https://github.com/chodeus/chub/commit/12de181a859e7f9f1f3f4d593e6467485f66e538))
* **settings:** default holiday schedule so a new Border Replacerr holiday saves ([e49aa08](https://github.com/chodeus/chub/commit/e49aa086116e9b5621bbece4330b28e22d22e084))
* **settings:** show the fanart.tv settings section in the UI ([f358a09](https://github.com/chodeus/chub/commit/f358a095189c9b425d45db40044a25d431a37058))
* **settings:** surface TMDB + fanart.tv API keys on the General page ([1e9a0e4](https://github.com/chodeus/chub/commit/1e9a0e49cffbd88c21d7e6521a1510656474bdf3))
* **setup:** correct the setup wizard tab title ([0d451fa](https://github.com/chodeus/chub/commit/0d451fafa995687a39b3411f482fc1065b9f6774))
* **setup:** hydrate existing Plex/*arr instances in the first-run wizard ([993de5c](https://github.com/chodeus/chub/commit/993de5c3ea021840a2c976f6012168084d58dead))
* **stats:** derive Lidarr has_content from track files for accurate library stats ([87b5193](https://github.com/chodeus/chub/commit/87b51938efb047745ca28bc612ef374f20f1092b))
* **stats:** exclude unmonitored-artist albums from Lidarr Missing ([d51ca52](https://github.com/chodeus/chub/commit/d51ca5215c4a63a99b4c2b05780391882e21d5c2))
* **stats:** normalize instance source case (title-cased source broke labels/order/freshness) ([603b338](https://github.com/chodeus/chub/commit/603b3389acdfdf77bd0754d3ea602233ad766dc3))
* **stats:** normalize media_cache.source at the write boundary ([4302581](https://github.com/chodeus/chub/commit/43025814423568c4e086057468f75b03d884c6aa))
* **stats:** read the matched_posters_stats key so Top contributors renders ([71eaba4](https://github.com/chodeus/chub/commit/71eaba4ab882a9e90f0b10da5751879f14cf3826))
* **stats:** release-gate Missing + add Upcoming; drop Statistics refresh ([38e10b8](https://github.com/chodeus/chub/commit/38e10b86f37bc5ee7acf7ab91569895643ef0f37))
* **sync_gdrive:** bind priority on the search-only refresh path ([f35f8bd](https://github.com/chodeus/chub/commit/f35f8bdbaea04cd1a4fe405358ce261de9dae4d0))
* **sync:** drop redundant rclone --exclude that triggered an ERROR log ([71bd0c7](https://github.com/chodeus/chub/commit/71bd0c778a2922cf2f30b2d734e923ca4f9572e1))
* **ui:** fidelity pass — match mock bar tracks, shadows, radii, accents ([eb29d3b](https://github.com/chodeus/chub/commit/eb29d3bacc96923efb5307754d34f8a8234a88ae))
* **ui:** honor conditional field visibility in Module Settings ([aa1384c](https://github.com/chodeus/chub/commit/aa1384c0ae594b1decaacd89b4b5850c18b76e6d))
* **ui:** live-walkthrough polish ([caa65be](https://github.com/chodeus/chub/commit/caa65be864a37b31831a0a08c5e74712b65f072c))
* **ui:** poll the jobs list while active so the duration timer doesn't overshoot ([e74571d](https://github.com/chodeus/chub/commit/e74571d67282818367573f152b80f5559b70263f))
* **ui:** preserve unrecognized instance strings on save in InstancesField ([4c1a7ef](https://github.com/chodeus/chub/commit/4c1a7ef05f5c8b5ee3c4121041025e6399bf3758))
* **ui:** restore functionality dropped during the redesign ([c82bd27](https://github.com/chodeus/chub/commit/c82bd27b3e6a49ebbfaf0cc4fc1ed2250f52f78e))
* **ui:** show Asset Renamerr in module settings (CONFIG_MODULE_KEYS) ([4195dcc](https://github.com/chodeus/chub/commit/4195dcc2f8ca8e6f17d29067acd93e05ebc6ea74))
* **unmatched-assets:** count in-library items with a stale unreleased status ([3f8adfa](https://github.com/chodeus/chub/commit/3f8adfa013036825495f2425d2025fbaa0b3116a))
* **unmatched:** artwork view polish + failure reasons + state-reset endpoint ([233e5f1](https://github.com/chodeus/chub/commit/233e5f123242b5295048395bdbca5778693bf3fd))
* **unmatched:** label show season rows in the artwork table ([34b91bd](https://github.com/chodeus/chub/commit/34b91bd500bad0d9f6128ad32866888e1a815673))
* **unmatched:** move recently-matched provenance stamp to the poster top-left ([a296278](https://github.com/chodeus/chub/commit/a296278367f82781f9615be81b39d72f7633dc84))
* **unmatched:** restore per-season detail + secondary external ids ([dc0d82d](https://github.com/chodeus/chub/commit/dc0d82d3355ba023a46d2e18c0162a18cf0ebfa8))
* **upload:** resolve posters against live Plex when absent from the cache ([1cbe48d](https://github.com/chodeus/chub/commit/1cbe48d45e0231edcd347d2caa1057942530eadb))
* **webhooks,upload:** close webhook + plex-upload reliability gaps ([0ba1fc5](https://github.com/chodeus/chub/commit/0ba1fc53396a3bbe723afce0b1a5cd4cadf550ad))
* **webhooks:** annotate best-effort empty-except clauses ([f189e35](https://github.com/chodeus/chub/commit/f189e35d84c3a564df5912c8aab11a7b8a8256df))
* **webhooks:** differentiate same-IP arr instances by payload instanceName ([266f249](https://github.com/chodeus/chub/commit/266f2496ec542129c41b40c33f2618a8fce3f2a0))
* **webhooks:** don't re-send the rename notification on upload retries ([227364d](https://github.com/chodeus/chub/commit/227364dfb38848d240779a66598c177b239e07c9))
* **webhooks:** drop phantom import events, align setup docs with Sonarr/Radarr ([7514552](https://github.com/chodeus/chub/commit/7514552021b255088bc97d03678cbc5c5a8bc901))
* **webhooks:** drop the duplicate rename-step notification ([3e23401](https://github.com/chodeus/chub/commit/3e23401432247ddad6b19f574adaa4c4cfa1a968))
* **webhooks:** match arr instance by resolved peer IP, not host+port string ([b4b8009](https://github.com/chodeus/chub/commit/b4b8009e41f05ec9e109fcd03ead31b466251b8b))
* **webhooks:** notify on the upload outcome, not the rename step ([da17729](https://github.com/chodeus/chub/commit/da17729ee1a062bf5aafb5ae017a942ecb699c2a))
* **webhooks:** run auto-provisioning off the event loop ([0c8876d](https://github.com/chodeus/chub/commit/0c8876dfbc465ec6de1e6bdc2511745924dc4b6b))
* **webhooks:** stop clobbering per-season has_content/monitored on upsert ([5da5ae8](https://github.com/chodeus/chub/commit/5da5ae8358c5b590296d17d3e55c2e33dd2fc09d))
* **webhooks:** verify-after-write so a landed provision isn't reported failed ([9d12dd1](https://github.com/chodeus/chub/commit/9d12dd19de176b652670036df47465d388cce8a6))
* **worker:** scope startup job reset to the worker's own partition ([70f67a8](https://github.com/chodeus/chub/commit/70f67a8fabcde17b17d1b813bb0cadf85e3e2970))


### Performance

* **api:** offload blocking handlers off the event loop, part 1 (WS-1) ([32a7142](https://github.com/chodeus/chub/commit/32a7142238c1440f93b75da5cfd611b043024918))
* **api:** offload duplicate-resolve + duplicate-members handlers (N8, N9) ([abdf4da](https://github.com/chodeus/chub/commit/abdf4dadc6a493d107e0a94a6601ae57c6a1d159))
* **api:** offload poster apply/upload/optimize handlers (P2, WS-1) ([a29a111](https://github.com/chodeus/chub/commit/a29a111967d470e8f4b11bebf5172eec647b1f37))
* **api:** offload remaining blocking handlers, part 2 (WS-1) ([c153d24](https://github.com/chodeus/chub/commit/c153d24b3a114bf91c3098967ecf6afbdf53030b))
* **arr:** parallelize Sonarr/Lidarr sub-item fetching; run upgradinatorr instances concurrently ([e273d3a](https://github.com/chodeus/chub/commit/e273d3ae9ebe474550f16b3f4d020f340eaf177c))
* **asset_renamerr:** resolve Plex artwork targets via a shared guid-first index ([0fa2a9d](https://github.com/chodeus/chub/commit/0fa2a9d6b3c65bbd4ea50ac30f7d9ec134123cae))
* **asset:** cache fanart.tv URLs (2-day TTL) to kill the per-run refetch storm ([c36ca6c](https://github.com/chodeus/chub/commit/c36ca6c72a1162b604e8e97a85da6279891651a6))
* **asset:** fold per-image_type local lookups into one fetch ([#3](https://github.com/chodeus/chub/issues/3)) ([cb3d5d3](https://github.com/chodeus/chub/commit/cb3d5d3673f429f121fca796190dd4e7e965cb97))
* **asset:** preload media_asset_matches + thread-safe fanart client ([a7294ac](https://github.com/chodeus/chub/commit/a7294ac046e8f120bfe1c6a657fc6c355c21479b))
* **asset:** reuse one read connection across the resolve loop (Option A) ([2fb7f61](https://github.com/chodeus/chub/commit/2fb7f6178a58ee36ea903e7eab48a0a078db7591))
* **border:** add skip-gate so unchanged posters aren't re-encoded ([61352b8](https://github.com/chodeus/chub/commit/61352b80f06843d5da9851da603d73ac3f4793eb))
* **border:** parallelize processing, atomic same-fs writes, real content compare ([7d78886](https://github.com/chodeus/chub/commit/7d78886d55f7e3541f3b42797eb72ab4df01c411))
* eliminate O(n×m)/O(n²) hot loops and parallelize independent I/O ([60ed5f1](https://github.com/chodeus/chub/commit/60ed5f1c829277e89ae725f7107d46b06f07deea))
* **instances:** drop the live wanted/missing call from the Instances page ([ab0b1f5](https://github.com/chodeus/chub/commit/ab0b1f57c149b5cbef33614506d1bbc76fa96eb2))
* **jobs:** per-phase progress windows so the bar advances through every phase ([9cd4944](https://github.com/chodeus/chub/commit/9cd49444ca06eff7794de29cf8c808fd2283db32))
* **labelarr:** build plex mapping once per bulk sync (P3, WS-4) ([27ea5a8](https://github.com/chodeus/chub/commit/27ea5a89b81872ca47233a4a6ac71d58d52d7ee9))
* **match:** skip match-phase row writes when the result is unchanged ([10c99a2](https://github.com/chodeus/chub/commit/10c99a26d8faf337497cf07d8bae8ffdfcacc90b))
* **pipeline:** batch cache writes, honor synchronous=NORMAL, skip redundant gdrive work ([2a00938](https://github.com/chodeus/chub/commit/2a00938c18a2736881e0b2643fb3450fe4b5c248))
* **poster_renamerr:** skip re-staging unchanged posters on the plex path ([e1d0cee](https://github.com/chodeus/chub/commit/e1d0ceec874e009715897f8f45d9654028d87857))
* **webhooks:** skip the Plex-availability wait when it can't help ([6f956f7](https://github.com/chodeus/chub/commit/6f956f7b9579b9c0b2d7a0abe64848858f310e86))


### Refactoring

* **asset_renamerr:** warn-once on unsupported types + honor print_only_renames ([87f20bf](https://github.com/chodeus/chub/commit/87f20bfd507907f02359bf71412e7b462f7dee3c))
* **asset:** drop the fanart.tv response cache ([1098527](https://github.com/chodeus/chub/commit/1098527c609619938bc394acb710f20c4ad94d28))
* **border:** remove redundant Holiday-only mode (skip) option ([c42d165](https://github.com/chodeus/chub/commit/c42d16562510993b18de880ad0ca8936b1e7f180))
* **config:** drop transitional plex_scope legacy validator ([5a3dba5](https://github.com/chodeus/chub/commit/5a3dba5da3c02ecfd20a54ab322ee8032afac078))
* consolidate duplicated logic (fixes clear-logo bloat-deletion bug) ([e93dd77](https://github.com/chodeus/chub/commit/e93dd772cf0b2f0414adb155c43b9262030c4b18))
* **css:** remove vestigial class labels and fix invented hover classes ([b12537a](https://github.com/chodeus/chub/commit/b12537af81a6210ed34e25881d78a2f83bbce53a))
* **instances:** drop the service-type badge from instance rows ([64f307c](https://github.com/chodeus/chub/commit/64f307ccefdd6ba97a26687c5453c3f2840115d1))
* **plex:** route all snapshot refreshes through the TTL guard ([4e03d3c](https://github.com/chodeus/chub/commit/4e03d3c60ddbd192cc5864459144808d5891eb7b))
* **poster-cleanarr:** logger param + guard parity + move/both-id tests for stale pass ([9b90402](https://github.com/chodeus/chub/commit/9b904028a00abcac305c15ce5d16d813b631fa37))
* remove email notifications (keep Discord + Notifiarr) ([f44af63](https://github.com/chodeus/chub/commit/f44af63495dcc699d32d9e64b267dc3114105ff1))
* **webhook:** consolidate season-scan wait into wait_for_plex_availability ([dc8e893](https://github.com/chodeus/chub/commit/dc8e893bc7f6e5c8cf3e09f1a4b08c9cc2029ed0))


### Documentation

* **notify:** correct stale ErrorNotifyHandler startup message ([fd72ba8](https://github.com/chodeus/chub/commit/fd72ba86972a648c21d6c6b154116595d09d5ef2))
* plan for Poster Cleanarr stale/orphan UI feature ([ec5a9cc](https://github.com/chodeus/chub/commit/ec5a9cce41c53d678ab86beaa36f223e1a2265e7))
* **plan:** backend plan (1/3) for plex_scope + lock match_collections encoding ([1e3ba28](https://github.com/chodeus/chub/commit/1e3ba2866fc2f95b068b9bc88e86ba9b58ee91d0))
* **plan:** expand runtime consumer coverage (Task 3b) after Task 1 review ([a4a7a7f](https://github.com/chodeus/chub/commit/a4a7a7f3bcca556f3e530d00d3268ee8595313a0))
* **plan:** frontend (2/3) + cleanup (3/3) plan for plex_scope ([63467b4](https://github.com/chodeus/chub/commit/63467b4fd042e7c658894f43bc778dccf6bbd15b))
* **poster-cleanarr:** document stale fields in cleanup API + note stale shares orphan instances ([2cac890](https://github.com/chodeus/chub/commit/2cac89041ac8414c079b687b5277c838a60120c3))
* **readme:** condense security section and trim WHY-heavy prose ([0dae9f1](https://github.com/chodeus/chub/commit/0dae9f11ace3c2377644eca2947188a59fc20020))
* **readme:** drop security section + alpha tag, add DAPS-differences section ([8f0010b](https://github.com/chodeus/chub/commit/8f0010bde52e49c95de5f9cfc0960d9d57b59020))
* **readme:** reframe DAPS section as improvements, broaden coverage ([f44c351](https://github.com/chodeus/chub/commit/f44c3517dba394a715cdc671e0d0a35617329364))
* **settings:** shorten Clean orphan assets tooltip ([9b03a65](https://github.com/chodeus/chub/commit/9b03a6537626ad7affa6256532f384c716728a50))
* **spec:** central Plex instance + library catalog with per-module plex_scope ([0905fa7](https://github.com/chodeus/chub/commit/0905fa73c959a2a9979c38d70f5e0197a4478319))

## [2.42.0](https://github.com/chodeus/chub/compare/v2.41.1...v2.42.0) (2026-07-23)


### Features

* **gdrive-presets:** add füsen CL2K drive ([acffe65](https://github.com/chodeus/chub/commit/acffe651c51cd486d602221bcbdfe09c14f2c9e3))
* **gdrive-presets:** add füsen CL2K drive ([b53177a](https://github.com/chodeus/chub/commit/b53177afa747b0fa73f617df9d8286cb38ccb4ed))
* **search:** accept colon id tags and bare numeric ids in search queries ([e68c1c2](https://github.com/chodeus/chub/commit/e68c1c28a41b7b68c504fc003e3017bcb8967d2a))
* **search:** colon id tags, bare numeric ids, and a search-syntax hint ([2e59a1f](https://github.com/chodeus/chub/commit/2e59a1f5f3bef273a388260a04fac4d19f1d794f))
* **search:** id search by colon tags and bare numeric ids in Assets Search ([47de04d](https://github.com/chodeus/chub/commit/47de04df09c116fa0893f2e36c21fa476a192e20))


### Bug Fixes

* **deps:** pin Pygments 2.20.0 (unpinned transitive of shipped pytest) ([decb5fb](https://github.com/chodeus/chub/commit/decb5fb5d36b058d8f0c637b0e6b767e6823525d))
* **security:** harden CodeQL-flagged regex and fanart URL construction ([edae09a](https://github.com/chodeus/chub/commit/edae09ab294987309dda13dd0f9636d744ce98bd))

## [2.41.1](https://github.com/chodeus/chub/compare/v2.41.0...v2.41.1) (2026-07-20)


### Bug Fixes

* **deps:** update all non-major dependencies ([#342](https://github.com/chodeus/chub/issues/342)) ([9446273](https://github.com/chodeus/chub/commit/9446273e709aa899abfd13427154557b97bd45b5))
* **poster_renamerr:** report only genuine Plex uploads and stop steady-state border churn ([#356](https://github.com/chodeus/chub/issues/356)) ([687a1b8](https://github.com/chodeus/chub/commit/687a1b8f37eccbb17c89841d4134ffab02935ecf))

## [2.41.0](https://github.com/chodeus/chub/compare/v2.40.0...v2.41.0) (2026-07-14)


### Features

* **asset-renamerr:** two-column config settings page ([447a612](https://github.com/chodeus/chub/commit/447a612562dbe071b3e2b1a0406818a19dc742fe))
* **plex-maintenance:** two-column config settings page ([e475ff4](https://github.com/chodeus/chub/commit/e475ff4b978dbb99f8cb461dd2f2f7aa764c432a))
* **poster-cleanarr:** library opt-out, hide music "(unknown)" clutter, clearer asset-pass settings ([c6d8bea](https://github.com/chodeus/chub/commit/c6d8bead55947462ea48548f2572d697851251c1))
* **poster-cleanarr:** show section-toggle descriptions, split the bloat-pass settings ([4ce0a2d](https://github.com/chodeus/chub/commit/4ce0a2db854189d6b45238e323300ab7192f22f8))
* **poster-cleanarr:** two-column config page with pass cards and help tooltips ([d0682e0](https://github.com/chodeus/chub/commit/d0682e025c75e2c269f0dada954677e376e16928))
* **poster-renamerr:** two-column config settings page ([ce36a4f](https://github.com/chodeus/chub/commit/ce36a4fad64e1b0b0c3c038e504977e78e8438d4))


### Bug Fixes

* **deps:** update all non-major dependencies ([#335](https://github.com/chodeus/chub/issues/335)) ([58022c8](https://github.com/chodeus/chub/commit/58022c873664e2ae74790cb64634dc29faae90d4))
* **notifications:** honor Discord retry_after and summarize huge runs ([3ca7f2a](https://github.com/chodeus/chub/commit/3ca7f2a0eba5c55f36fde0c12b1e68aeec075696))

## [2.40.0](https://github.com/chodeus/chub/compare/v2.39.0...v2.40.0) (2026-07-10)


### Features

* **webhooks:** auto-detect the provisioning base URL + fix precedence ([1aa1252](https://github.com/chodeus/chub/commit/1aa1252c9ede4e465be341c91bc7e6b8ba7a1d09))
* **webhooks:** payload-first routing + auto-provision poster webhook into *arrs ([f218ead](https://github.com/chodeus/chub/commit/f218ead782f2db8181ba1e115ae18baa9f76278e))


### Bug Fixes

* **ui:** poll the jobs list while active so the duration timer doesn't overshoot ([24e3f0d](https://github.com/chodeus/chub/commit/24e3f0d063b9c2e0db24343940c73030abae76a1))
* **upload:** resolve posters against live Plex when absent from the cache ([d87513d](https://github.com/chodeus/chub/commit/d87513d3670ceb5a32500e386e20d03700ff7116))
* **webhooks:** annotate best-effort empty-except clauses ([92a2cc2](https://github.com/chodeus/chub/commit/92a2cc25baa90d07d30e4bb8213ae1d58b23c35c))
* **webhooks:** don't re-send the rename notification on upload retries ([a82bff6](https://github.com/chodeus/chub/commit/a82bff6b9c99db6e7febe85c1aed788b271070a6))
* **webhooks:** drop the duplicate rename-step notification ([54b2f60](https://github.com/chodeus/chub/commit/54b2f60bc4f3ea6a5ce7527e5fd2ce71f3bc4070))
* **webhooks:** notify on the upload outcome, not the rename step ([481d6a9](https://github.com/chodeus/chub/commit/481d6a9c39ea497dd241a6fb861ba73e89efb6d5))
* **webhooks:** run auto-provisioning off the event loop ([aa9c747](https://github.com/chodeus/chub/commit/aa9c747482d97cf4b136ddb6331074994ff1225a))
* **webhooks:** verify-after-write so a landed provision isn't reported failed ([2319803](https://github.com/chodeus/chub/commit/2319803b74a8058e03b408107b8a8f48868266a9))

## [2.39.0](https://github.com/chodeus/chub/compare/v2.38.1...v2.39.0) (2026-07-10)


### Features

* **config:** reveal saved secrets on demand via the eye toggle ([04bcd9d](https://github.com/chodeus/chub/commit/04bcd9d1f1a032175251e1c3c28655c2adf21296))
* **instances:** opt-in gate for Plex libraries before they surface in CHUB ([aa12689](https://github.com/chodeus/chub/commit/aa12689ec6c7118a631e0c94180cec0b2e112722))
* **labelarr:** replace free-text library field with an opt-in picker ([8da6c8c](https://github.com/chodeus/chub/commit/8da6c8c463334a7818f0ffe6881ed3819047ae6a))
* **webhooks:** honor X-Forwarded-For from trusted proxies for instance matching ([a60e97b](https://github.com/chodeus/chub/commit/a60e97b9c952e835f56ce20189f6dff4099692fd))


### Bug Fixes

* **auth:** render posters via token-less URLs when auth is not configured ([4873d40](https://github.com/chodeus/chub/commit/4873d401aa50d8d0a6360a017ce5d5ebba18fec6))
* **poster_renamerr:** library-aware plex skip-unchanged + lock the match phase ([7a416bb](https://github.com/chodeus/chub/commit/7a416bb8aa0150d76fe42fd17d1d844f6133c508))
* **posters:** don't send Discord/Notifiarr alert for unconfigured plex_path ([140e19f](https://github.com/chodeus/chub/commit/140e19f8c184e898d030c40e462cf35aae9929b4))
* **unmatched:** restore per-season detail + secondary external ids ([2554caf](https://github.com/chodeus/chub/commit/2554cafe03c9319f511a536ca3e9020095100ef7))
* **webhooks,upload:** close webhook + plex-upload reliability gaps ([9e5b967](https://github.com/chodeus/chub/commit/9e5b967641722c20d0099b52651ddd6ca11aa2d1))
* **webhooks:** differentiate same-IP arr instances by payload instanceName ([0bdf629](https://github.com/chodeus/chub/commit/0bdf629eb56abe6ece6fc901f0a1fbd241ea9c27))
* **webhooks:** drop phantom import events, align setup docs with Sonarr/Radarr ([45fa5fe](https://github.com/chodeus/chub/commit/45fa5fe70d0ce00969481d27a236cad74147984f))
* **webhooks:** match arr instance by resolved peer IP, not host+port string ([6ac6247](https://github.com/chodeus/chub/commit/6ac6247254dea3661627474f29b3e98a7975a474))


### Performance

* **poster_renamerr:** skip re-staging unchanged posters on the plex path ([3cbb12e](https://github.com/chodeus/chub/commit/3cbb12e12dae67c8c0f4fd962c4c2c49ccb50f3e))
* **webhooks:** skip the Plex-availability wait when it can't help ([2a6ebd1](https://github.com/chodeus/chub/commit/2a6ebd1d52f1bba9a51621a7227c42cc16afd136))

## [2.38.1](https://github.com/chodeus/chub/compare/v2.38.0...v2.38.1) (2026-07-04)


### Bug Fixes

* **posters:** delete the configured gdrive folder, not the request path ([743a087](https://github.com/chodeus/chub/commit/743a087230f9e60a487571c8ff968af209d39e04))

## [2.38.0](https://github.com/chodeus/chub/compare/v2.37.0...v2.38.0) (2026-07-04)


### Features

* **extensions:** add stream_prefixes() hook for extension stream routes ([7ce6841](https://github.com/chodeus/chub/commit/7ce684101687a3060d68b1938a98ffbc9d86078d))


### Bug Fixes

* LIKE escaping, optimize clobber-guard, transient-cache, 0-is-falsy, logout cache, CI perms ([01237f6](https://github.com/chodeus/chub/commit/01237f6adbcffc6381d97fca45ff2a76256742c9))
* **plex_metadata:** don't cache a bloat scan when the Plex DB copy failed ([0518256](https://github.com/chodeus/chub/commit/0518256751ebf691571bf35fc433b3890f7b7647))

## [2.37.0](https://github.com/chodeus/chub/compare/v2.36.0...v2.37.0) (2026-07-01)


### Features

* **auth:** short-lived scoped stream tokens for image/SSE URLs ([1b5e8e4](https://github.com/chodeus/chub/commit/1b5e8e46daafad2d349d0b9b1b65cebce7eba5fd))
* **fields:** add generic action_button settings field type ([b4ec1e2](https://github.com/chodeus/chub/commit/b4ec1e2c403fa9f12f156493551f35f037609ebf))
* **gdrive:** confirm drive removal and optionally delete local folder + cache rows ([5182971](https://github.com/chodeus/chub/commit/5182971a3e4083fa683e56d349598ab51611ef5c))
* **instances:** support renaming an instance end to end ([49c65ed](https://github.com/chodeus/chub/commit/49c65ed3d9e7b60230e125dba6f70d90445a200b))
* **posters:** unified, readable CL2K/MM2K provenance stamp ([9ff36a6](https://github.com/chodeus/chub/commit/9ff36a6aa622460a5da446c07c3ff56f795b570c))
* **stats:** count Sonarr at the episode level (shows/seasons as context) ([00044c8](https://github.com/chodeus/chub/commit/00044c8213653051e64f40e1097900c382b5782b))
* **stats:** order Artist above Album in By type ([dc9d94e](https://github.com/chodeus/chub/commit/dc9d94e819fcd8bbbb92b1e6da2b411cd1c0ecef))
* **stats:** pair By type with By instance, consistent card borders ([df45aa7](https://github.com/chodeus/chub/commit/df45aa7d29318618a30fe8ea1bcbd418bc39f6f2))
* **stats:** regroup Library Statistics by synced instance ([e1853ac](https://github.com/chodeus/chub/commit/e1853ac2bbbb8a7f4b57a59c1c89319c3d2791a0))
* **stats:** show Sonarr Series AND Episodes as separate cards ([ac3fa0e](https://github.com/chodeus/chub/commit/ac3fa0e74ef3a70e8f8380f885f02ba24da7104d))
* **sync:** background instance reconciliation from the Instances page ([0618712](https://github.com/chodeus/chub/commit/06187121d53097caf9f05c838b2dbfc06a9c1839))
* **webhooks:** banner when ingest endpoints are unauthenticated ([8177c90](https://github.com/chodeus/chub/commit/8177c900a77ebdee954fd8c1de81a6838c5b04b2))


### Bug Fixes

* **auth:** keep the stream token warm + rebuild image URLs when it lands ([ac0758b](https://github.com/chodeus/chub/commit/ac0758bf92a0e4d27638a8683dc0f277ab86af60))
* backend correctness and reliability fixes ([03191ea](https://github.com/chodeus/chub/commit/03191ead5422f7871ee4d1c2aa86a5a17a18cefa))
* **config:** split a shared-webhook notification destination by event ([1908da5](https://github.com/chodeus/chub/commit/1908da560ef49fbb52fd1617135155dc956ad53f))
* **data-loss:** guard destructive poster/nohl/upload paths ([274588c](https://github.com/chodeus/chub/commit/274588ce7b7d0df4cef43d871bbf0d6c9298dd9d))
* **docker:** download rclone to its checksummed filename so sha256sum -c passes ([10dddfa](https://github.com/chodeus/chub/commit/10dddfad573968b6e160876c3eb530bc5785b1f0))
* **fields:** action_button ignores a stale result after its row changes ([89b3586](https://github.com/chodeus/chub/commit/89b35865286446686a90c6fc68d7d555643b935e))
* **frontend:** cache invalidation, callbacks, and falsy-value bugs ([5219923](https://github.com/chodeus/chub/commit/52199231c1f01a6430a0a7c35caa6a6d1e48d4cd))
* **frontend:** FloatField 0-value, duplicates-resolve cache, instance keys ([583bb7e](https://github.com/chodeus/chub/commit/583bb7ebb090dbc7fbd65a4a6168c30138f25d92))
* **instances:** case-insensitive source on rename + composite UI-state keys ([079bdce](https://github.com/chodeus/chub/commit/079bdce8252738a56783a9a625cc47efd5ea1b8a))
* **instances:** disable redirects on SSRF-validated health/test probes ([184ffd9](https://github.com/chodeus/chub/commit/184ffd97d99dfde95c6c93a24c6a0a00b217478e))
* **instances:** don't clobber stored API key with the redacted placeholder ([3878d05](https://github.com/chodeus/chub/commit/3878d058b7d2e7b993fff812e2cddc7e2b022997))
* **instances:** read sync_schedule from the nested section response ([4d1666e](https://github.com/chodeus/chub/commit/4d1666e93f9131d0c0a75b6348d0d3d056718060))
* **instances:** resolve redacted API key by URL when renaming ([837e23b](https://github.com/chodeus/chub/commit/837e23bc02db20d432f989ac78f89ef4b36248ae))
* **jobs:** collapse a composite trigger to its readable base ([876e854](https://github.com/chodeus/chub/commit/876e854cada3229f99090df15a234a9d05c91cbd))
* **jobs:** humanize the job-type label ([28967b8](https://github.com/chodeus/chub/commit/28967b8129c6b4a7183c5b8d205a575453e13f4f))
* **logger:** redact secrets in tracebacks, yaml OAuth tokens, and the Notifiarr key ([05ef9df](https://github.com/chodeus/chub/commit/05ef9df8eddbe233efe2aab86a459faa3327dffa))
* **modules:** redact secrets in GET /api/modules/{name} ([8dc024c](https://github.com/chodeus/chub/commit/8dc024c4f341debc8d277963f1b983f1e6827c96))
* **notify:** stop redacted placeholder clobbering destination webhooks ([b38a128](https://github.com/chodeus/chub/commit/b38a1289fa17418f0ca24e2ef9aa17c7e12d22e2))
* **schedule:** reject malformed schedule strings at the API ([40e2233](https://github.com/chodeus/chub/commit/40e22334899a2d3fef2fe996f6606d9e3e8039d1))
* **security:** fail closed on config error + warn on unauthenticated webhook ingest ([23336ef](https://github.com/chodeus/chub/commit/23336ef7f488ca3fd991276aeac440950294b019))
* **security:** fail-closed SSRF guard, key-exfil + redirect guards, auth-section write block ([012ce45](https://github.com/chodeus/chub/commit/012ce4563b04fdbcae94482e30a23b7d45accaad))
* **stats:** derive Lidarr has_content from track files for accurate library stats ([28dfaff](https://github.com/chodeus/chub/commit/28dfaff77ac7adb7504d8a5b0a57f5b0b24df433))
* **stats:** exclude unmonitored-artist albums from Lidarr Missing ([a4e6eab](https://github.com/chodeus/chub/commit/a4e6eabf726189efcca898bf229a3b0c1900a645))
* **stats:** normalize instance source case (title-cased source broke labels/order/freshness) ([3b4165e](https://github.com/chodeus/chub/commit/3b4165ee504391a5d9492ef45fbbe1d72a7dd9fb))
* **stats:** normalize media_cache.source at the write boundary ([5236831](https://github.com/chodeus/chub/commit/52368316db4f284708b21f1ae3d8e6c702e7264e))
* **stats:** read the matched_posters_stats key so Top contributors renders ([ae30605](https://github.com/chodeus/chub/commit/ae30605394ebbd262a8fc10af6b8523f0e46fba0))
* **stats:** release-gate Missing + add Upcoming; drop Statistics refresh ([a46a416](https://github.com/chodeus/chub/commit/a46a4160a2b675e5a92222063a89a157a70342dc))
* **unmatched:** move recently-matched provenance stamp to the poster top-left ([3f04e25](https://github.com/chodeus/chub/commit/3f04e258c7b9981808b1e368a4d6b1c9b9da81be))
* **webhooks:** stop clobbering per-season has_content/monitored on upsert ([5ab982c](https://github.com/chodeus/chub/commit/5ab982cfe701ad003f9ca134ba72e56a24014672))
* **worker:** scope startup job reset to the worker's own partition ([982a7b1](https://github.com/chodeus/chub/commit/982a7b15cdd92ef774ec79b275be1b7271e46aa5))


### Performance

* **instances:** drop the live wanted/missing call from the Instances page ([cc5a075](https://github.com/chodeus/chub/commit/cc5a07561db2f1843789d1d845d2a6c091344c12))


### Refactoring

* **instances:** drop the service-type badge from instance rows ([838dab5](https://github.com/chodeus/chub/commit/838dab5976f2ea79ab6671a7a1cead4894bbb189))

## [2.36.0](https://github.com/chodeus/chub/compare/v2.35.0...v2.36.0) (2026-06-28)


### Features

* **assets-search:** cache-coverage stats strip from the mock ([eebbe71](https://github.com/chodeus/chub/commit/eebbe7197b1e8f2ed0948f117489e8939b82e0d0))
* **assets:** library-size stat + fix last-sync parsing (YYYYMMDD) ([cfdeb69](https://github.com/chodeus/chub/commit/cfdeb69517812e579afc5962d82e72d043afb39a))
* **cleanarr:** restyle Poster Cleanarr config to the 3-pass mock ([31302d1](https://github.com/chodeus/chub/commit/31302d13e7f5941e15c96cc3a01cf1deb664427f))
* **extensions:** generic notification_formatters() hook for extension modules ([bc20215](https://github.com/chodeus/chub/commit/bc202156f6671510bdc43be64af8a9cb5b51264c))
* **fields:** always-expanded card mode for array-object configs ([1218ff9](https://github.com/chodeus/chub/commit/1218ff98403e546de7d41a83e75a3edaef47eaeb))
* **fields:** contextual add-button label on array-object fields ([8238414](https://github.com/chodeus/chub/commit/823841469b81c6cfd0dfcad880eb891d3dde2e95))
* **gdrive-presets:** add MajorGiant CL2K drive ([01bb26c](https://github.com/chodeus/chub/commit/01bb26c2aa95d9e0c5abf9469c0f1e4943fe33b3))
* **gdrive:** use GDrive drives for poster matching by default ([2aefff5](https://github.com/chodeus/chub/commit/2aefff51e97973a6118d12fd844c2f9fca2c243b))
* **instances:** render *arr instance multi-select as pills ([5630de6](https://github.com/chodeus/chub/commit/5630de6a03838d93162c3520249d328456208fae))
* **jobs:** TRIGGER column + Clear&gt;30d to match mock ([d8932ee](https://github.com/chodeus/chub/commit/d8932eeeb4096c9da4513ac3ecad95566dbb3e25))
* **labelarr:** bespoke mapping card with enabled toggle + label chips ([bddac4d](https://github.com/chodeus/chub/commit/bddac4dfa025131c943dec0d2ca09c0eb0116f18))
* **labelarr:** inline mapping CRUD with per-mapping enable toggle ([651d296](https://github.com/chodeus/chub/commit/651d2963fa854819e64e05f15f0944acba8e7fdb))
* **layout:** remove the global breadcrumb bar ([94d5951](https://github.com/chodeus/chub/commit/94d5951f67abe623c16640e1f3ae76b866005b83))
* **library-manage:** restyle to the new mock ([254e7e4](https://github.com/chodeus/chub/commit/254e7e4a31eaeaa2d7c59a5d916cad5e742a01a9))
* **login:** restyle to redesign mock ([aebdeb3](https://github.com/chodeus/chub/commit/aebdeb34f24b79d86187ab3b826c6adf20576068))
* **manage:** mock duplicate grid with lazy copies + bulk delete ([a017b09](https://github.com/chodeus/chub/commit/a017b093967e680441ad38f85b8926901d137424))
* **module-configs:** lead with primary content, demote Log Level to Logging ([46ad67e](https://github.com/chodeus/chub/commit/46ad67e62723333f9460282aabf92bed794dc0ff))
* **module-configs:** section Renameinatorr/Nohl/Health Checkarr/Jduparr/Plex Maintenance to mocks ([a3621ea](https://github.com/chodeus/chub/commit/a3621ea37fb9b6ca067fc51a5fdcea5376de80fa))
* **modules:** hub grid + per-module routes + hard-disable (Phase 1) ([4bd95eb](https://github.com/chodeus/chub/commit/4bd95ebf49de6197b2e4ea331de4e62e0c9b5d86))
* **modules:** module-settings shell + boolean toggle rows (Phase 2) ([c3d67c0](https://github.com/chodeus/chub/commit/c3d67c019fe598ec415b3f811e78bef3d76d89d9))
* **nestarr:** surface path_mapping as expanded cards ([4af24e4](https://github.com/chodeus/chub/commit/4af24e46970bb0f356316c9ed0e4055f7fd7d87e))
* **notifications:** per-destination model, migration, dispatch + redesigned page ([9c0f5f6](https://github.com/chodeus/chub/commit/9c0f5f6d6899b5c4cb8c876a50cc98c9f12f4135))
* **notifications:** reshape Notifications to mock channel rows ([0c9e667](https://github.com/chodeus/chub/commit/0c9e66749bb8f29e7c993fc0b1463808e852ceb6))
* **plex-scope:** add-posters / match-collections as toggle rows ([97a7838](https://github.com/chodeus/chub/commit/97a78380b8afd10bc44dcd08c1d9a3aa747637e0))
* **poster-renamerr:** priority badges + bottom-wins hint on source dirs ([443740d](https://github.com/chodeus/chub/commit/443740d0e43782005bdebc4c1ab32e6d30e63400))
* **poster-renamerr:** reorder config to mock (Output → Source → Targets → Chained actions) ([59476cc](https://github.com/chodeus/chub/commit/59476cc61cbf3c0fb3b77ee2d1b2fd72693a1d88))
* **poster-stats:** adopt mock layout + Top contributors ([d3752e6](https://github.com/chodeus/chub/commit/d3752e667a4f6fd247f04901b1508cdd74cfcfff))
* **schedule:** drop stats strip, add base/profile/block legend ([93d1d9c](https://github.com/chodeus/chub/commit/93d1d9c1ca6c89fcc2f26e56ee235ecbfb06632f))
* **schedule:** remove the per-module Test button ([f7366d0](https://github.com/chodeus/chub/commit/f7366d0b2c50cc12cb8c0a62a169583f97486d39))
* **settings:** accent picker + Appearance section on General ([3e20375](https://github.com/chodeus/chub/commit/3e203750b267f7397ace802ea0a5295e2d02c3b5))
* **settings:** drop the Settings cards hub; re-run wizard from General ([622076b](https://github.com/chodeus/chub/commit/622076b232262976b2b87babdc914bbeda285b13))
* **settings:** extension-aware Modules hub + Schedule, add runnable:false flag ([983aec0](https://github.com/chodeus/chub/commit/983aec0465c3b3d4f50d3b90d4d8e1f22af9a994))
* **settings:** extension-aware Notifications + Dashboard; share config-only helper ([2d6cd5e](https://github.com/chodeus/chub/commit/2d6cd5e0ac050fbd359f83aff365563d304dfbe4))
* **settings:** generic 'requires' precondition warning on module config pages ([c0ec00f](https://github.com/chodeus/chub/commit/c0ec00f82a1fb5d4f862aa44f6a538e5b26fb5a1))
* **settings:** label-left/control-right field rows (Phase 2b) ([c230c2c](https://github.com/chodeus/chub/commit/c230c2cc45eb2ec7445079174d191e089eb370e7))
* **settings:** segmented field type for either/or enums ([5e99e03](https://github.com/chodeus/chub/commit/5e99e0370a91d07dd501cdbf0026bc5d09cf38a3))
* **sync-gdrive:** bespoke drive table matching the mock ([3ce8528](https://github.com/chodeus/chub/commit/3ce8528281a14dfadaf3db1d61496010ed359f2b))
* **sync-gdrive:** section config to mock (Authentication → Options) ([6c9599c](https://github.com/chodeus/chub/commit/6c9599c746a278c2cc9438a59010b1f02267543e))
* **system:** rebuild System settings to redesign mock ([eae1705](https://github.com/chodeus/chub/commit/eae17054e399549bd6e8b16e6a1c066327fc9899))
* **ui:** add the mock's filter ⌘F hint to the Logs search input ([aafadeb](https://github.com/chodeus/chub/commit/aafadebd4dce8437501caedcccd280c4acbcab1d))
* **ui:** polish Settings sub-components to match mocks ([290b08a](https://github.com/chodeus/chub/commit/290b08a34eb0cd211a28f7fcf8fc3ac82e73df52))
* **ui:** redesign Assets Search ([bf9594c](https://github.com/chodeus/chub/commit/bf9594c97a6f43c7566e9b48413ddde93047c826))
* **ui:** redesign Border Replacerr + Logs ([4bc1ec0](https://github.com/chodeus/chub/commit/4bc1ec0bff8ab34a5d8f3d83b9269bd9d12a9b9a))
* **ui:** redesign dashboard as a dense ops board ([b7c84af](https://github.com/chodeus/chub/commit/b7c84af9b8df2f36a877e18779e656dd98d3574b))
* **ui:** redesign foundation — fonts, palette tokens, sidebar shell ([f24005f](https://github.com/chodeus/chub/commit/f24005f28ac55bc90b904c3f817f60dad2545091))
* **ui:** redesign GDrive Sources + Poster Statistics ([59a1f34](https://github.com/chodeus/chub/commit/59a1f34409fc8b616c5249f2e074ea1affe95daf))
* **ui:** redesign Library section (search, manage, stats, label sync) ([d86e27e](https://github.com/chodeus/chub/commit/d86e27ea2e8975c4e61af51ba9324196f2b4e3ea))
* **ui:** redesign Poster Cleanarr + Unmatched Assets (master-detail) ([73ba3a6](https://github.com/chodeus/chub/commit/73ba3a699016b3fbb38d3fdc362df8dd24011f0b))
* **ui:** redesign Settings Jobs — mono stat strip + filter pills ([ce93e60](https://github.com/chodeus/chub/commit/ce93e60cc3f1db8044deac3c78523dbdfe93856c))
* **ui:** redesign Settings page shells (Instances/General/Modules/Notifications/Schedule) ([2742d82](https://github.com/chodeus/chub/commit/2742d827dc6f864ca4d1089b43e78af929aafe34))
* **ui:** redesign Settings shell — dense PageHeader + hub/System/Webhooks ([8376587](https://github.com/chodeus/chub/commit/8376587408d49f4b38bfa8483365fcdf91d5575b))
* **ui:** remove Quick start section from the dashboard ([abe7a14](https://github.com/chodeus/chub/commit/abe7a14a6fab2724b966d13e9c1c7c5317ae303d))
* **ui:** retire desktop top header; tighten Logs to match mock ([441050b](https://github.com/chodeus/chub/commit/441050bcbf59dde578d12adbb36e4f09db19fb2f))
* **unmatched:** drop blank thumb; add CL2K build action to artwork rows ([631ca10](https://github.com/chodeus/chub/commit/631ca10f2c32ec625cf45fabf3218ed48a4b208b))
* **unmatched:** match Additional-artwork view to the poster styling ([1ec28f4](https://github.com/chodeus/chub/commit/1ec28f4a6ab2d154f74b9ab8457d536c03ece3a5))
* **unmatched:** reshape unmatched list to redesign mock ([52a3a0e](https://github.com/chodeus/chub/commit/52a3a0e0e0f3a6a0097b12363636bdb9f53efd65))
* **upgradinatorr:** bespoke profile card matching the mock ([25b010c](https://github.com/chodeus/chub/commit/25b010c4c43ff0adfbbfba3250d5f6a48a638a52))
* **webhooks:** reshape Webhooks page to mock + per-origin telemetry ([d0412fd](https://github.com/chodeus/chub/commit/d0412fd8bf1a35400aa0cb4a6e615f33b6960de6))


### Bug Fixes

* **accent:** use text-on-color (not hard-coded white) on brand surfaces ([7bdbdb1](https://github.com/chodeus/chub/commit/7bdbdb1e3026cea4d8e9395eb4fe7c1493b5b0df))
* **badge:** stop dev prop-validation false-positives ([fc942bd](https://github.com/chodeus/chub/commit/fc942bd7af0670abd6946bb402ce9a76b7088a40))
* **deps:** update all non-major dependencies ([#274](https://github.com/chodeus/chub/issues/274)) ([6e694ef](https://github.com/chodeus/chub/commit/6e694efab591b301ca0c0ad19f05618d6580fe5c))
* **deps:** update all non-major dependencies ([#275](https://github.com/chodeus/chub/issues/275)) ([13986c4](https://github.com/chodeus/chub/commit/13986c460dd8bc620744fb00b6ae3fc7449d401c))
* **dirlist:** compact flat path rows to match the module mocks ([4bf4606](https://github.com/chodeus/chub/commit/4bf4606d2a969ee3d4e09111f79d257b1bfccd51))
* **gdrive-table:** flat fields in inset rows to match the mock ([8039be3](https://github.com/chodeus/chub/commit/8039be30779f9ad6b037aa13be6c1fe67e2c4714))
* **jobs+modules:** mock-style job actions; drop module-config breadcrumb ([c36fd06](https://github.com/chodeus/chub/commit/c36fd06fb2c73ca31d8a329675d697386e8adc58))
* **logger:** attach module file handler regardless of root handlers ([21b6379](https://github.com/chodeus/chub/commit/21b6379dc01f85b210b192eebeb1903df926777d))
* **logs:** don't list stale on-disk dirs as log modules ([97d38da](https://github.com/chodeus/chub/commit/97d38da851c515c2cfbc200dd4effbaf03fc4b95))
* **logs:** list config-only extension modules (e.g. cl2k_maker) ([dab7f45](https://github.com/chodeus/chub/commit/dab7f4505793d0e63f795fc24e007870af97130d))
* **matching:** strip *arr "(0)" unknown-year placeholder in normalization ([6b08881](https://github.com/chodeus/chub/commit/6b0888194722381a95a862b78b59854827b0e5eb))
* **mobile:** stat strips wrap instead of overlapping on narrow screens ([ad43180](https://github.com/chodeus/chub/commit/ad43180352f0a95e635108755597f7cdb8cd21e2))
* **poster-cleanarr:** mock-style checkboxes + variant status tags ([48ac575](https://github.com/chodeus/chub/commit/48ac575ac5093fffc65d082c20ad13fcce98340a))
* **poster-cleanarr:** show cached scan on return, don't re-scan ([9dfdb6e](https://github.com/chodeus/chub/commit/9dfdb6e8bae3ce6971c5631fcd79147f74ca78be))
* **poster-stats:** guard non-array detail data (page crash) ([b4b04da](https://github.com/chodeus/chub/commit/b4b04da0d64734ea2dbf0fae6f39e612a52f9b27))
* **settings:** surface TMDB + fanart.tv API keys on the General page ([61b11bf](https://github.com/chodeus/chub/commit/61b11bf6f1f8fba3a02cd2bed2b4a60812f4cea0))
* **ui:** fidelity pass — match mock bar tracks, shadows, radii, accents ([53ed50a](https://github.com/chodeus/chub/commit/53ed50a68f59aa770937a9d6692a0d5e67ece6a6))
* **ui:** live-walkthrough polish ([c6607e4](https://github.com/chodeus/chub/commit/c6607e412fcd28e0b7d674a92135b20a085c9ccd))
* **ui:** restore functionality dropped during the redesign ([94ccf47](https://github.com/chodeus/chub/commit/94ccf4747fa3d10d519018fc99abcb6e3ea3a074))


### Documentation

* **notify:** correct stale ErrorNotifyHandler startup message ([075c73f](https://github.com/chodeus/chub/commit/075c73fc5d564fa6f6def21fc100a8a50fd5b040))

## [2.35.0](https://github.com/chodeus/chub/compare/v2.34.0...v2.35.0) (2026-06-25)


### Features

* **tmdb:** add circuit breaker to abort runs on sustained TMDB outage ([7fa6fd0](https://github.com/chodeus/chub/commit/7fa6fd0ac674bfed1bf869d5f871a2079f1623be))


### Bug Fixes

* **poster_cleanarr:** run metadata scans off the event loop via background jobs ([cae5baf](https://github.com/chodeus/chub/commit/cae5baf963a03616643961215302ceb15277cec5))
* **security:** harden Plex XML parsing and break config import cycle ([0068389](https://github.com/chodeus/chub/commit/00683896f1b37efa3e11fefd4312c735f20ae729))


### Documentation

* **readme:** condense security section and trim WHY-heavy prose ([31e5341](https://github.com/chodeus/chub/commit/31e534136b1c3e66a91a3a8cd00923b3640ef954))
* **readme:** drop security section + alpha tag, add DAPS-differences section ([6c686a0](https://github.com/chodeus/chub/commit/6c686a0859b4088cfe30f02c596374719ea8cbed))
* **readme:** reframe DAPS section as improvements, broaden coverage ([1eda047](https://github.com/chodeus/chub/commit/1eda04728e756abc67a514ec18f4d2d990951ccd))

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
