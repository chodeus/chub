# Credits

CHUB stands on the shoulders of a lot of prior work. This page collects every acknowledgement that belongs in the project.

## DAPS — the direct lineage

CHUB is a fork of **[DAPS](https://github.com/Drazzilb08/daps)** by **[Drazzilb08](https://github.com/Drazzilb08)**. Every one of the twelve scheduled modules — `poster_renamerr`, `jduparr`, `nohl`, `upgradinatorr`, `labelarr`, `renameinatorr`, `health_checkarr`, `border_replacerr`, `nestarr`, `poster_cleanarr`, `unmatched_assets`, `sync_gdrive` — originated in DAPS. The Plex/ARR integration patterns, the config layout, and the core idea of "one dashboard for every chore" are all DAPS inheritance.

What CHUB adds on top:

- A rebranded identity (logos, palette, typography) and a RoomSketch-inspired UI redesign
- Cooperative job cancellation on eleven of the twelve modules
- Live run-state updates via server-sent events at `/api/modules/events`
- Inline media editing with a per-field audit trail
- Duplicate resolution UI with fuzzy matching
- System-health snapshots captured every 6 hours with 30-day retention
- Token-bucket login rate limiter, SSRF guard, path-safety validation, expanded log redaction
- Webhook origin tracking and optional shared-secret authentication
- Batch media import, time-windowed stats, low-resolution poster filter, on-the-fly image resize and convert
- Activity digest and cleanup-candidates endpoints

None of this replaces what DAPS is — it's a fork with a different direction, not a successor. If you want the original, go to [Drazzilb08/daps](https://github.com/Drazzilb08/daps).

## Inspiration

- **[RoomSketch dashboard](https://dribbble.com/shots/27040128)** — visual reference for the floating content panel, pastel quick-start badges, and small-caps sidebar sections.
- **[sl1ckbe3ts palette](https://lospec.com/palette-list/sl1ck-bets)** — source for the cool/indigo theme colours.
- **Kometa / PMM** — the asset folder conventions `poster_renamerr` targets.
- **The Servarr family** (Radarr / Sonarr / Lidarr) — the API surface CHUB integrates against.

## Third-party Python libraries

From `requirements.txt`:

- `fastapi` + `starlette` + `uvicorn` — HTTP server and routing
- `pydantic` — config schema + validation
- `PlexAPI` — Plex client
- `qbittorrent-api` — download-client hooks
- `Pillow` — image resize, border painting, format conversion
- `bcrypt` + `PyJWT` — auth primitives
- `apprise` — notification fan-out
- `croniter` — cron expression evaluation
- `requests`, `requests-oauthlib`, `oauthlib` — ARR and Google Drive OAuth
- `watchdog` — filesystem watching
- `PyYAML` + `ruamel.yaml.clib` — config I/O
- `pathvalidate` + `Unidecode` — filename sanitisation
- `tqdm` + `prettytable` — progress and CLI output

Full list with versions in `requirements.txt`.

## Third-party frontend libraries

From `frontend/package.json`:

- **React 19** + **React DOM** — UI runtime
- **React Router DOM 7** — routing
- **Vite 6** — dev server and build tool
- **PropTypes** — runtime prop validation
- **Manrope** + **Inter** (Google Fonts) — typography

## Icons and fonts

- **Lucide** — sidebar and in-page icons
- **Manrope** by Mikhail Sharanda — display font
- **Inter** by Rasmus Andersson — body font

## Contributors

See the [chodeus/chub contributors graph](https://github.com/chodeus/chub/graphs/contributors) once the repo is public. PRs welcome — open an issue first for anything larger than a small patch.

## License

CHUB is MIT-licensed. See [LICENSE](https://github.com/chodeus/chub/blob/main/LICENSE).

DAPS is also MIT-licensed. CHUB's license text acknowledges the original copyright holder alongside chodeus.

Thanks to everyone whose work made CHUB possible.
