// web/static/js/settings/settings_schema.js
export const SETTINGS_SCHEMA = [
    {
        key: 'tmdb',
        label: 'TMDB',
        fields: [
            {
                key: 'apikey',
                label: 'API Key',
                type: 'password',
                required: false,
                placeholder: 'TMDB v3 API key',
                description:
                    'TMDB v3 API key. Get one free at themoviedb.org/settings/api. When set, Chub resolves missing TMDB IDs for unmatched assets and improves poster matching across the app.',
            },
            {
                key: 'cache_expiration',
                label: 'Cache Expiration (days)',
                type: 'number',
                required: false,
                description:
                    'How long to cache external→TMDB ID lookups before re-querying. TMDB enforces ~50 req/s and per-day quotas, so this cache keeps repeat syncs from burning API budget. Default 60.',
            },
        ],
    },
    {
        key: 'fanart',
        label: 'fanart.tv',
        fields: [
            {
                key: 'client_key',
                label: 'Personal API Key',
                type: 'password',
                required: false,
                placeholder: 'fanart.tv personal API key',
                description:
                    'Your personal fanart.tv API key. Required to use fanart.tv as an Asset Renamerr source for logos + backgrounds — a personal key authenticates on its own, so it is all CHUB needs. It also cuts the delay for newly-added artwork from 7 days to 2 (immediate for VIP accounts). Get one free at fanart.tv/get-an-api-key (Personal API Keys).',
            },
            {
                key: 'cache_expiration',
                label: 'Cache Expiration (days)',
                type: 'number',
                required: false,
                description:
                    'How long to cache resolved fanart.tv logo/background URLs before re-querying. fanart.tv asks that apps make no more requests than necessary, so this cache keeps repeat runs from re-hitting their servers. Default 2 — matching the personal key’s own 2-day delay for newly-added art, so a shorter window cannot surface anything newer anyway.',
            },
        ],
    },
    {
        key: 'sync_gdrive',
        label: 'Sync Gdrive',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description: 'Set the logging verbosity for Google Drive sync.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description:
                    'Pass --dry-run to rclone — log every file that would be copied or deleted without touching the local filesystem.',
            },
            {
                key: 'verbose',
                label: 'Verbose',
                type: 'check_box',
                description:
                    'Log every file rclone copies, deletes, updates, or renames. Useful for tracing what changed; can be noisy on large syncs.',
            },
            {
                key: 'gdrive_sa_location',
                label: 'Service Account Location',
                type: 'text',
                required: false,
                description:
                    'Path to a Google Drive service-account JSON keyfile. If this is set, the three OAuth fields below are ignored — choose ONE method.',
            },
            {
                key: 'client_id',
                label: 'Client ID',
                type: 'password',
                required: false,
                placeholder: 'Place Client ID Here',
                conditional: {
                    field: 'gdrive_sa_location',
                    condition: 'is_empty',
                },
                description:
                    'OAuth client ID. Only used when no service-account file is set above.',
            },
            {
                key: 'client_secret',
                label: 'Client Secret',
                type: 'password',
                required: false,
                conditional: {
                    field: 'gdrive_sa_location',
                    condition: 'is_empty',
                },
                description:
                    'OAuth client secret. Only used when no service-account file is set above.',
            },
            {
                key: 'token',
                label: 'Token (JSON)',
                type: 'json',
                required: false,
                placeholder:
                    '{\n  "access_token": "ya29.a0AfH6SMBEXAMPLEEXAMPLETOKEN",\n  "refresh_token": "1",\n  "scope": "https://www.googleapis.com/auth/drive",\n  "token_type": "Bearer",\n  "expiry_date": 1712345678901\n}',
                conditional: {
                    field: 'gdrive_sa_location',
                    condition: 'is_empty',
                },
                description:
                    'OAuth2 token JSON. Only used when no service-account file is set above.',
            },
            {
                key: 'gdrive_list',
                label: 'Google Drive List',
                type: 'object_array',
                displayType: 'gdrive',
                required: false,
                description: 'Each entry contains id, location, and name.',

                fields: [
                    {
                        key: 'preset',
                        label: 'Gdrive Presets',
                        type: 'presets',
                        presetType: 'gdrive',
                        presetUrl: '/api/gdrive-presets',
                        identifierField: 'name',
                        moduleConfigKey: 'gdrive_list',
                        targetFields: ['name', 'id'],
                        required: false,
                        exclude_on_save: true,
                        description: 'Select a preset configuration for Google Drive.',
                        presetHandler: true,
                    },
                    {
                        key: 'name',
                        label: 'Name',
                        type: 'text',
                        required: true,
                        description: 'Friendly name for this Google Drive entry.',
                    },
                    {
                        key: 'id',
                        label: 'GDrive ID',
                        type: 'text',
                        required: true,
                        description: 'Unique ID of the Google Drive folder or file.',
                    },
                    {
                        key: 'location',
                        label: 'Location',
                        type: 'dir',
                        required: true,

                        description: 'Local directory to sync with the specified Google Drive ID.',
                    },
                ],
            },
        ],
    },

    {
        key: 'poster_renamerr',
        label: 'Poster Renamerr',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description:
                    '"debug" prints per-file decisions and is useful when investigating a missing match; "info" is the normal cron-friendly level.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description:
                    'Walk the full pipeline and log every action that would be taken — but write nothing to disk and upload nothing to Plex.',
            },
            {
                key: 'print_only_renames',
                label: 'Log only renamed files',
                type: 'check_box',
                description:
                    'Quiet the log by suppressing entries for files that are already up to date. Only newly renamed/copied files are logged.',
            },
            // ─── Source ────────────────────────────────────────────────
            {
                key: 'source_dirs',
                label: 'Source Directories',
                type: 'dirlist_dragdrop',
                section: 'Source',
                required: true,
                description:
                    'Folders scanned for poster assets. Drag to set priority — later directories win when multiple sources have a poster for the same item (bottom of the list takes precedence).',
            },
            {
                key: 'sync_posters',
                label: 'Sync from Google Drive first',
                type: 'check_box',
                section: 'Source',
                description:
                    'Run Sync Gdrive before each Poster Renamerr run so the source directories are up to date. Requires Sync Gdrive to be configured.',
            },
            // ─── Apply ─────────────────────────────────────────────────
            {
                key: 'apply_method',
                label: 'Apply Method',
                type: 'dropdown',
                section: 'Apply',
                options: [
                    { value: 'plex', label: 'Plex' },
                    { value: 'kometa', label: 'Kometa' },
                ],
                required: true,
                description:
                    'Where matched posters go (either/or). "Plex" uploads posters straight to Plex for the instances whose "Upload to this Plex instance" box is ticked below — nothing is written to disk. "Kometa" renames/copies posters into the Destination Directory for Kometa to apply — no Plex upload. The Destination Directory / File Action / Asset folders settings apply to the "Kometa" method.',
            },
            {
                key: 'destination_dir',
                label: 'Destination Directory',
                type: 'dir',
                section: 'Apply',
                required: true,
                description:
                    'Kometa method: where renamed posters are written. Plex/Kometa-compatible asset folder structure when "Asset folders" is enabled below.',
            },
            {
                key: 'action_type',
                label: 'File Action',
                type: 'dropdown',
                section: 'Apply',
                options: ['copy', 'move', 'hardlink', 'symlink'],
                required: true,
                description:
                    'Kometa method: how matched posters reach the destination. "hardlink" is fastest and saves disk space when source and destination are on the same filesystem; "copy" is safest if you are unsure.',
            },
            {
                key: 'asset_folders',
                label: 'Asset folders (per-show)',
                type: 'check_box',
                section: 'Apply',
                description:
                    'Kometa method: enable Plex-style folder layout: destination/<Show Name>/poster.jpg + Season01.jpg. When off, files are flat: destination/<Show Name>_Season01.jpg.',
            },
            // ─── Pipeline ──────────────────────────────────────────────
            {
                key: 'run_border_replacerr',
                label: 'Run Border Replacerr after rename',
                type: 'check_box',
                section: 'Pipeline',
                description:
                    'After files are renamed, hand the manifest to Border Replacerr so it can recolor or strip the white TPDB border on just those posters. Configure colors in the Border Replacerr module.',
            },
            {
                key: 'run_asset_renamerr',
                label: 'Run Asset Renamerr after rename',
                type: 'check_box',
                section: 'Pipeline',
                description:
                    "After posters are processed, run Asset Renamerr in the same pass to apply logos, square art, backgrounds, and banners — reusing this run's Google Drive sync, source scan, and media/Plex data so nothing is fetched twice. Configure the asset types, sources, and apply method in the Asset Renamerr module.",
            },
            {
                key: 'upload_delay_ms',
                label: 'Upload delay (ms)',
                type: 'number',
                section: 'Pipeline',
                description:
                    'Optional pause after each poster uploaded to Plex, to be gentle on the server during large runs. 0 = no delay (default). Only applied after an actual upload, never after a skip. Try 50 if your Plex struggles under bursts.',
            },
            {
                key: 'clean_orphan_assets',
                label: 'Clean orphan assets after rename',
                type: 'check_box',
                section: 'Pipeline',
                description:
                    "After renaming, walk the destination directory and act on every poster file with no parent media in the configured instances — i.e. an orphan asset. A file is kept if its {tmdb-N}/{tvdb-N} id tag matches the library OR its title matches; it's flagged only when both miss (a stale id whose title still matches is kept). Source directories are deliberately out of scope: gdrive-synced source dirs would just re-download deleted files on the next sync, and personal source dirs aren't CHUB's to delete from. (Not to be confused with the Unmatched Assets module, which reports media missing a poster — the opposite direction.) The action taken (report / move / remove) follows the Orphan Assets Mode set in the Poster Cleanarr module, so a single setting governs both this post-rename pass and a standalone Cleanarr run.",
            },
            {
                key: 'report_unmatched_assets',
                label: 'Report unmatched assets',
                type: 'check_box',
                section: 'Pipeline',
                description:
                    'Log a summary of source posters that could not be matched to any media. Useful for spotting filename typos or missing IDs on the asset side.',
            },
            // ─── Targets ───────────────────────────────────────────────
            {
                key: 'instances',
                label: 'Instances',
                type: 'instances',
                section: 'Targets',
                required: true,
                add_posters_option: true,
                instance_types: ['plex', 'radarr', 'sonarr', 'lidarr'],
                description:
                    'Radarr/Sonarr/Lidarr instances supply the media list to match against. Plex instances additionally receive uploaded posters when "Upload posters to this Plex instance" is enabled per-instance.',
            },
        ],
    },

    {
        key: 'asset_renamerr',
        label: 'Asset Renamerr',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description:
                    'Set the logging verbosity. "debug" prints per-item source resolution and apply decisions.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description:
                    'Walk the full pipeline and log every action that would be taken — but write nothing to disk and upload nothing to Plex.',
            },
            {
                key: 'print_only_renames',
                label: 'Log only applied assets',
                type: 'check_box',
                description:
                    'Quiet the log by suppressing entries for assets that were already up to date.',
            },
            // ─── Asset types ───────────────────────────────────────────
            {
                key: 'asset_types',
                label: 'Asset Types',
                type: 'array',
                section: 'Assets',
                suggestions: ['logo', 'background', 'squareart'],
                allowCustom: false,
                placeholder: 'Add asset type…',
                description:
                    'Which additional asset types to manage. Support varies by Apply Method: logo and background work on BOTH "direct" and "kometa"; squareart works on "direct" ONLY (Kometa asset directories do not read square art, so squareart is skipped with a warning under "kometa"). Defaults to logo + background.',
            },
            // ─── Source ────────────────────────────────────────────────
            {
                key: 'sources',
                label: 'Primary Source',
                type: 'primary_source',
                section: 'Source',
                options: [
                    { value: 'local', label: 'Prefer local files (fanart.tv fallback)' },
                    { value: 'fanart', label: 'Prefer fanart.tv (local fallback)' },
                ],
                required: true,
                description:
                    'Which image source to prefer; the other is automatically used as a fallback when the preferred source has no image for an item. "local" = files scanned from Source Directories (g-drive synced). "fanart" = logos + backgrounds from fanart.tv, ranked by community likes (requires your fanart.tv personal API key below; supplies logo + background only — square art always comes from local files).',
            },
            {
                key: 'source_dirs',
                label: 'Source Directories',
                type: 'dirlist_dragdrop',
                section: 'Source',
                description:
                    'Folders scanned for asset files named like "Title (Year) {tmdb-123} - Logo.png". Drag to set priority — later directories win when multiple sources have the same asset (bottom takes precedence). Used by the "local" source.',
            },
            {
                key: 'sync_assets',
                label: 'Sync from Google Drive first',
                type: 'check_box',
                section: 'Source',
                description:
                    'Run Sync Gdrive before each standalone Asset Renamerr run so the source directories are up to date. Not needed when running via Poster Renamerr\'s "Run Asset Renamerr after rename" (that pass reuses the poster sync).',
            },
            {
                key: 'tmdb_language',
                label: 'Image Languages (priority order)',
                type: 'multiselect',
                section: 'Source',
                placeholder: 'Add language…',
                options: [
                    { value: 'en', label: 'English (en)' },
                    { value: 'es', label: 'Spanish (es)' },
                    { value: 'fr', label: 'French (fr)' },
                    { value: 'de', label: 'German (de)' },
                    { value: 'it', label: 'Italian (it)' },
                    { value: 'pt', label: 'Portuguese (pt)' },
                    { value: 'nl', label: 'Dutch (nl)' },
                    { value: 'ja', label: 'Japanese (ja)' },
                    { value: 'ko', label: 'Korean (ko)' },
                    { value: 'zh', label: 'Chinese (zh)' },
                    { value: 'ru', label: 'Russian (ru)' },
                    { value: 'hi', label: 'Hindi (hi)' },
                    { value: 'ar', label: 'Arabic (ar)' },
                    { value: 'tr', label: 'Turkish (tr)' },
                    { value: 'pl', label: 'Polish (pl)' },
                    { value: 'sv', label: 'Swedish (sv)' },
                    { value: 'da', label: 'Danish (da)' },
                    { value: 'no', label: 'Norwegian (no)' },
                    { value: 'fi', label: 'Finnish (fi)' },
                    { value: 'cs', label: 'Czech (cs)' },
                    { value: 'el', label: 'Greek (el)' },
                    { value: 'he', label: 'Hebrew (he)' },
                    { value: 'th', label: 'Thai (th)' },
                    { value: 'id', label: 'Indonesian (id)' },
                    { value: 'uk', label: 'Ukrainian (uk)' },
                ],
                description:
                    'Preferred languages for fanart.tv image selection, in priority order (the order you add them) — the first available language wins, with language-neutral / textless art always allowed as a fallback. Logos prefer your languages then textless; backgrounds prefer textless then your languages. Within a tier, the most-liked image on fanart.tv wins.',
            },
            // ─── Apply ─────────────────────────────────────────────────
            {
                key: 'apply_method',
                label: 'Apply Method',
                type: 'dropdown',
                section: 'Apply',
                options: [
                    { value: 'plex', label: 'Plex' },
                    { value: 'kometa', label: 'Kometa' },
                ],
                required: true,
                description:
                    '"Plex" uploads images straight to Plex via plexapi — logo, background, and squareart — for the instances whose "Upload to this Plex instance" box is ticked below. "Kometa" renames/copies files into the Destination Directory using Kometa asset names (logo.ext, background.ext, and Season##_logo.ext for seasons) for Kometa to apply — Kometa reads only logo and background.',
            },
            {
                key: 'destination_dir',
                label: 'Destination Directory',
                type: 'dir',
                section: 'Apply',
                description:
                    'Kometa assets directory where renamed assets are written. Required when Apply Method is "kometa".',
            },
            {
                key: 'action_type',
                label: 'File Action',
                type: 'dropdown',
                section: 'Apply',
                options: ['copy', 'move', 'hardlink', 'symlink'],
                required: true,
                description:
                    'How matched assets reach the destination on the "kometa" path. "hardlink" is fastest and saves disk when source and destination share a filesystem; "copy" is safest.',
            },
            {
                key: 'asset_folders',
                label: 'Asset folders (per-title)',
                type: 'check_box',
                section: 'Apply',
                description:
                    'Kometa-style folder layout: destination/<Title (Year)>/logo.png. When off, files are flat: destination/<Title (Year)>_logo.png. Match this to your Kometa configuration.',
            },
            // ─── Targets ───────────────────────────────────────────────
            {
                key: 'instances',
                label: 'Instances',
                type: 'instances',
                section: 'Targets',
                required: true,
                add_posters_option: true,
                instance_types: ['plex', 'radarr', 'sonarr'],
                description:
                    'Radarr/Sonarr instances supply the media list to match against. On the "Plex" apply method, assets are uploaded only to Plex instances whose "Upload to this Plex instance" box is ticked; Plex instances also supply collections.',
            },
        ],
    },

    {
        key: 'border_replacerr',
        label: 'Border Replacerr',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description:
                    '"debug" prints per-poster crop/replace decisions; "info" is the normal cron-friendly level.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description:
                    'Walk the full pipeline and log every poster that would be re-bordered — but write nothing to disk.',
            },
            // ─── Paths ─────────────────────────────────────────────────
            {
                key: 'source_dirs',
                label: 'Source Directories',
                type: 'dirlist_dragdrop',
                section: 'Paths',
                description:
                    'Folders scanned for poster assets when Border Replacerr is run on its own (not via Poster Renamerr). Drag to set priority — later directories win when multiple sources have a poster for the same item (bottom of the list takes precedence).',
            },
            {
                key: 'destination_dir',
                label: 'Destination Directory',
                type: 'dir',
                section: 'Paths',
                description:
                    'Where re-bordered posters are written when Border Replacerr is run on its own. When triggered via Poster Renamerr, the manifest path is used instead and this field is ignored.',
            },
            // ─── Border ────────────────────────────────────────────────
            {
                key: 'border_width',
                label: 'Border Width (px)',
                type: 'number',
                section: 'Border',
                required: true,
                placeholder: '26',
                description:
                    'Pixels cropped from each edge before re-bordering. Posters that follow the TPDB standard ship with a 26px white border, so 26 is the right value for almost every library. Posters without a matching border will lose this much real artwork.',
            },
            {
                key: 'border_colors',
                label: 'Border Colors',
                type: 'color_list',
                section: 'Border',
                description:
                    'Default border colors used when no holiday window is active. Rotates through the list as posters are processed. Pick richer per-holiday palettes and themed border art on the Border Replacerr page.',
            },
            // ─── Holidays ──────────────────────────────────────────────
            {
                key: 'skip',
                label: 'Holiday-only mode',
                type: 'check_box',
                section: 'Holidays',
                description:
                    'When on, Border Replacerr only runs on days that fall inside an active holiday window below — outside those windows it skips the run entirely. Use this if you only want themed borders during holidays and would rather leave the default white border untouched the rest of the year.',
            },
            {
                key: 'holidays',
                label: 'Holidays',
                type: 'object_array',
                section: 'Holidays',
                displayType: 'replacerr',
                description:
                    "Add the holidays you want themed borders for and set their date windows here. Pick colors and themed border art on the Border Replacerr page — when today falls inside a holiday's window, that holiday's styling is used instead of the defaults.",
                fields: [
                    {
                        key: 'preset',
                        label: 'Holiday Presets',
                        type: 'presets',
                        presetType: 'holiday',
                        identifierField: 'name',
                        moduleConfigKey: 'holidays',
                        targetFields: ['name', 'schedule', 'colors'],
                        description:
                            'Picking a preset prefills name, date window, and default colors. Customize colors and pick border art on the Border Replacerr page.',
                        presetHandler: true,
                    },
                    {
                        key: 'name',
                        label: 'Holiday Name',
                        type: 'text',
                        required: true,
                        description: 'Name of the holiday for color override.',
                    },
                    {
                        key: 'schedule',
                        label: 'Schedule',
                        type: 'holiday_schedule',
                        required: false,
                        description: 'Schedule for when the holiday override is active.',
                    },
                ],
            },
            // ─── Filters ───────────────────────────────────────────────
            {
                key: 'exclusion_list',
                label: 'Exclusion List',
                type: 'textarea',
                section: 'Filters',
                description:
                    "Media titles to skip entirely (one per line). Matched against the poster's associated media title — useful for keeping a few specific shows on their original border.",
            },
            {
                key: 'ignore_folders',
                label: 'Ignore Folders',
                type: 'textarea',
                section: 'Filters',
                description:
                    'Source folder names to skip (one per line). Posters whose source folder matches any entry are left untouched.',
            },
        ],
    },

    {
        key: 'upgradinatorr',
        label: 'Upgradinatorr',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description: 'Set the logging verbosity for upgradinatorr.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description: 'Simulate upgrade actions without making changes.',
            },
            {
                key: 'instances_list',
                label: 'Instances List',
                type: 'object_array',
                displayType: 'upgradinatorr',

                description:
                    'Profiles can run with the main Upgradinatorr schedule or on their own schedule.',
                fields: [
                    {
                        key: 'enabled',
                        label: 'Enabled',
                        type: 'check_box',
                        defaultValue: true,
                        description:
                            'Uncheck to temporarily opt this profile out without deleting its settings. Disabled profiles are skipped on both scheduled and manual runs.',
                    },
                    {
                        key: 'label',
                        label: 'Profile Name',
                        type: 'text',
                        required: false,
                        placeholder: 'Movies 4K upgrades',
                        description:
                            'Optional display name used in the profile list and scheduler logs.',
                    },
                    {
                        key: 'instance',
                        label: 'Instance',
                        type: 'dropdown',
                        options_source: 'api_instances',
                        options_filter: ['radarr', 'sonarr', 'lidarr'],
                        required: true,
                        description: 'Select the instance to upgrade (Radarr, Sonarr, or Lidarr).',
                    },
                    {
                        key: 'schedule',
                        label: 'Profile Schedule',
                        type: 'schedule',
                        required: false,
                        description:
                            'Optional schedule for this profile. Leave empty to run only when the main Upgradinatorr schedule or Run button runs.',
                    },
                    {
                        key: 'search_mode',
                        label: 'Search Mode',
                        type: 'dropdown',
                        options: ['upgrade', 'missing', 'cutoff'],
                        defaultValue: 'upgrade',
                        required: false,
                        description:
                            'Upgrade: search all untagged items for better quality. Missing: search only items with no files. Cutoff: search items below quality profile cutoff.',
                    },
                    {
                        key: 'count_mode',
                        label: 'Count Mode',
                        type: 'dropdown',
                        options: ['series_artist', 'season_album'],
                        defaultValue: 'series_artist',
                        required: false,
                        conditional: {
                            field: 'instance',
                            condition: 'instance_type_in',
                            value: ['sonarr', 'lidarr'],
                            api_lookup: 'instances',
                        },
                        description:
                            'series_artist: Count caps how many series/artists are processed per run (every monitored season/album of each gets searched). season_album: Count caps the number of season/album searches — safer for trackers; partially-processed series/artists resume next run.',
                    },
                    {
                        key: 'count',
                        label: 'Count',
                        type: 'number',
                        required: true,
                        description:
                            'Items per run. Interpreted by Count Mode: series/artists (Radarr, or series_artist mode) or individual season/album searches (season_album mode).',
                    },
                    {
                        key: 'tag_name',
                        label: 'Tag Name',
                        type: 'text',
                        required: false,
                        defaultValue: 'checked',
                        placeholder: 'checked',
                        description:
                            'Marker tag Upgradinatorr adds after searching an item. Leave blank to use "checked".',
                    },
                    {
                        key: 'ignore_tag',
                        label: 'Ignore Tag',
                        type: 'text',
                        placeholder: 'ignore',
                        description:
                            'ARR tag used to exclude media from this profile. Leave blank to use "ignore".',
                    },
                    {
                        key: 'unattended',
                        label: 'Auto reset processed tag',
                        type: 'check_box',
                        description:
                            'When every eligible item has the marker tag, remove that marker tag and start the rotation again.',
                    },
                    {
                        key: 'season_monitored_threshold',
                        label: 'Season Monitored Threshold',
                        type: 'float',
                        required: true,
                        conditional: {
                            field: 'instance',
                            condition: 'instance_type_equals',
                            value: 'sonarr',
                            api_lookup: 'instances',
                        },
                        description:
                            'Minimum percentage of monitored seasons required (Sonarr only).',
                    },
                ],
            },
        ],
    },

    {
        key: 'renameinatorr',
        label: 'Renameinatorr',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['info', 'debug'],
                required: true,
                description: 'Set the logging verbosity for renameinatorr.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description: 'Simulate renaming without making changes.',
            },
            {
                key: 'rename_folders',
                label: 'Rename Folders',
                type: 'check_box',
                description: 'Enable to rename folders as well as files.',
            },
            {
                key: 'count',
                label: 'Count',
                type: 'number',
                description: 'Number of items to rename per operation.',
            },
            {
                key: 'radarr_count',
                label: 'Radarr Count',
                type: 'number',
                description: 'Number of Radarr items to process per run.',
            },
            {
                key: 'sonarr_count',
                label: 'Sonarr Count',
                type: 'number',
                description: 'Number of Sonarr items to process per run.',
            },
            {
                key: 'tag_name',
                label: 'Tag Name',
                type: 'text',
                description: 'Tag name to filter items for renaming.',
            },
            {
                key: 'enable_batching',
                label: 'Enable Batching',
                type: 'check_box',
                description: 'Enable batch processing for renaming.',
            },
            {
                key: 'instances',
                label: 'Instances',
                type: 'instances',
                required: true,
                instance_types: ['radarr', 'sonarr'],
                // Backend: RenameinatorrConfig.instances is List[str].
                valueFormat: 'string',
                description: 'List of Radarr and Sonarr instances to rename.',
            },
        ],
    },

    {
        key: 'nohl',
        label: 'Nohl',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description: 'Set the logging verbosity for Nohl module.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description: 'Simulate actions without making changes.',
            },
            {
                key: 'searches',
                label: 'Searches',
                type: 'number',
                required: true,
                description: 'Number of search operations to perform.',
            },
            {
                key: 'print_files',
                label: 'Print Files',
                type: 'check_box',
                description: 'Print file paths during operation.',
            },
            {
                key: 'source_dirs',
                label: 'Source Directories',
                type: 'dirlist_options',
                options: ['scan', 'resolve'],
                default_mode: 'resolve',
                required: true,

                description: 'Directories to scan or resolve for files.',
            },
            {
                key: 'exclude_profiles',
                label: 'Exclude Profiles',
                type: 'textarea',
                description: 'Profiles to exclude from processing.',
            },
            {
                key: 'exclude_movies',
                label: 'Exclude Movies',
                type: 'textarea',
                description: 'Movies to exclude from processing.',
            },
            {
                key: 'exclude_series',
                label: 'Exclude Series',
                type: 'textarea',
                description: 'Series to exclude from processing.',
            },
            {
                key: 'instances',
                label: 'Instances',
                type: 'instances',
                required: true,
                add_posters_option: false,
                instance_types: ['radarr', 'sonarr'],
                // Backend: NohlConfig.instances is List[str].
                valueFormat: 'string',
                description: 'Instances to apply Nohl logic to.',
            },
        ],
    },

    {
        key: 'labelarr',
        label: 'Labelarr',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description: 'Set the logging verbosity for labelarr.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description: 'Simulate label management actions without making changes.',
            },
            {
                key: 'mappings',
                label: 'Mappings',
                type: 'object_array',
                displayType: 'labelarr',

                description:
                    'Choose which Sonarr/Radarr tag becomes which Plex label, and on which Plex instance.',
                fields: [
                    {
                        key: 'app_instance',
                        label: 'App Instance',
                        type: 'dropdown',
                        options_source: 'api_instances',
                        options_filter: ['radarr', 'sonarr', 'lidarr'],
                        required: true,
                        description: 'Select the specific app instance for this mapping.',
                    },
                    {
                        key: 'labels',
                        label: 'Labels',
                        type: 'text',
                        required: true,
                        description: 'Labels to assign in this mapping.',
                    },
                    {
                        key: 'plex_instances',
                        label: 'Plex Instances',
                        type: 'instances',
                        required: true,
                        instance_types: ['plex'],
                        add_posters_option: false,
                        description: 'List of Plex instances to apply the labels to.',
                    },
                ],
            },
        ],
    },

    {
        key: 'health_checkarr',
        label: 'Health Checkarr',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['info', 'debug'],
                required: true,
                description: 'Set the logging verbosity for health checks.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description:
                    'Log what would be deleted from Radarr/Sonarr without actually deleting. Turn off to actually clean up media flagged as removed from TMDB/TVDB.',
            },
            {
                key: 'instances',
                label: 'Instances',
                type: 'instances',
                required: true,
                add_posters_option: false,
                instance_types: ['radarr', 'sonarr'],
                // Backend: HealthCheckarrConfig.instances is Optional[List[str]].
                valueFormat: 'string',
                // description: 'Instances to run health checks on.',
            },
        ],
    },

    {
        key: 'jduparr',
        label: 'Jduparr',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description: 'Set the logging verbosity for jduparr.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description: 'Simulate duplicate detection without making changes.',
            },
            {
                key: 'source_dirs',
                label: 'Source Directories',
                type: 'dirlist',
                required: true,

                description:
                    'Directories to scan together for duplicate media files. Duplicates across these directories can be hardlinked.',
            },
            {
                key: 'hash_database',
                label: 'Hash Database',
                type: 'text',
                description:
                    'Optional jdupes hash database file path. Leave blank unless you want jdupes to reuse a persistent hash cache.',
            },
        ],
    },

    {
        key: 'nestarr',
        label: 'Nestarr',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['info', 'debug'],
                required: true,
                description: 'Set the logging verbosity for nest detection.',
            },
            {
                key: 'library_mappings',
                label: 'Library Mappings',
                type: 'object_array',
                displayType: 'nestarr',
                description:
                    'Map Plex libraries to ARR instances to enable ARR↔Plex unmatched detection. Only mapped libraries are checked — unmapped libraries (e.g. Music) are excluded. Leave empty to keep unmatched detection off (nested and stray-file detection still run).',
                fields: [
                    {
                        key: 'arr_instance',
                        label: 'ARR Instance',
                        type: 'dropdown',
                        options_source: 'api_instances',
                        options_filter: ['radarr', 'sonarr', 'lidarr'],
                        required: true,
                        description:
                            'Select the Radarr, Sonarr, or Lidarr instance to compare against.',
                    },
                    {
                        key: 'plex_instances',
                        label: 'Plex Instances',
                        type: 'instances',
                        required: true,
                        instance_types: ['plex'],
                        add_posters_option: false,
                        description:
                            'Select Plex instances and the specific libraries to compare against this ARR instance.',
                    },
                ],
            },
            {
                key: 'path_mapping',
                label: 'Path Mapping',
                type: 'object_array',
                description:
                    'Map ARR container paths to CHUB-accessible paths for filesystem scanning. Only needed if containers use different volume mount points. Leave empty if all containers share the same media mounts.',
                fields: [
                    {
                        key: 'arr_path',
                        label: 'ARR Path Prefix',
                        type: 'text',
                        required: true,
                        placeholder: '/data',
                        description: 'Path prefix as seen inside the ARR container (e.g. /data).',
                    },
                    {
                        key: 'local_path',
                        label: 'CHUB Path Prefix',
                        type: 'text',
                        required: true,
                        placeholder: '/mnt/user/data',
                        description:
                            'Equivalent path as seen inside the CHUB container (e.g. /mnt/user/data).',
                    },
                ],
            },
        ],
    },

    {
        key: 'poster_cleanarr',
        label: 'Poster Cleanarr',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description: 'Set the logging verbosity for poster cleanup.',
            },
            {
                key: 'mode',
                label: 'Mode',
                type: 'dropdown',
                options: ['report', 'move', 'remove', 'restore', 'clear', 'nothing'],
                required: true,
                section: 'Plex Bloat Cleanup',
                description:
                    'Operation mode: report (dry run), move (recoverable), remove (permanent), restore (recover moved), clear (delete restore dir), nothing (skip images).',
            },
            {
                key: 'plex_path',
                label: 'Plex Path',
                type: 'text',
                required: true,
                section: 'Plex Bloat Cleanup',
                description:
                    "Path inside the CHUB container that points at your Plex Media Server's data dir " +
                    "— the folder that directly contains 'Metadata/', 'Cache/', 'Plug-in Support/', etc. " +
                    "Typical Docker setup: mount the host's 'Library/Application Support/Plex Media Server/' " +
                    'to /plex and enter /plex here.',
            },
            {
                key: 'local_db',
                label: 'Local Database',
                type: 'check_box',
                section: 'Plex Bloat Cleanup',
                description:
                    'Copy the Plex database locally instead of downloading via API. Requires Plex to be stopped.',
            },
            {
                key: 'use_existing_db',
                label: 'Use Existing Database',
                type: 'check_box',
                section: 'Plex Bloat Cleanup',
                description: 'Reuse existing database copy if less than 2 hours old.',
            },
            {
                key: 'ignore_running',
                label: 'Ignore Running Check',
                type: 'check_box',
                section: 'Plex Bloat Cleanup',
                description: 'Bypass the Plex running detection when using local database mode.',
            },
            {
                key: 'overlays_only',
                label: 'Overlays Only',
                type: 'check_box',
                section: 'Plex Bloat Cleanup',
                description:
                    'Only act on files that carry the Kometa overlay EXIF tag. Custom-uploaded posters/art (which lack the tag) are left alone. Safer for Kometa users — files without the marker are skipped, not deleted.',
            },
            {
                key: 'sleep',
                label: 'Sleep Between Operations',
                type: 'number',
                section: 'Plex Bloat Cleanup',
                description: 'Seconds to wait between operations (default: 60).',
            },
            {
                key: 'timeout',
                label: 'Connection Timeout',
                type: 'number',
                section: 'Plex Bloat Cleanup',
                description: 'Plex connection timeout in seconds (default: 600).',
            },
            {
                key: 'instances',
                label: 'Plex Instance(s)',
                type: 'instances',
                required: true,
                instance_types: ['plex'],
                valueFormat: 'string',
                section: 'Plex Bloat Cleanup',
                description:
                    'Plex instance(s) whose metadata directory is scanned for bloat images. The bloat pass uses the first Plex instance selected here.',
            },
            {
                key: 'orphan_assets_enabled',
                label: 'Enable Orphan Asset Cleanup',
                type: 'check_box',
                section: 'Orphan Asset Cleanup',
                description:
                    "Walk Asset Directories and act on poster files with no parent media in the Library Instances below — orphan = asset with no parent media. A file is kept if its {tmdb-N}/{tvdb-N} id tag matches the library OR its title matches; it's flagged only when both miss. Use Ignore Titles below to exempt specific posters. (Inverse direction of the Unmatched Assets module, which reports media missing a poster.) Comparison set is read from CHUB's media cache (populated by poster_renamerr) — run renamerr first if the cache is stale.",
            },
            {
                key: 'orphan_assets_mode',
                label: 'Orphan Mode',
                type: 'dropdown',
                options: ['report', 'move', 'remove'],
                section: 'Orphan Asset Cleanup',
                description:
                    'report (log only), move (relocate to a hidden .chub_orphan_restore subdir inside each asset_dir, fully recoverable), remove (permanent delete).',
            },
            {
                key: 'asset_dirs',
                label: 'Asset Directories',
                type: 'dirlist_dragdrop',
                section: 'Orphan Asset Cleanup',
                description:
                    "Directories to scan when this standalone orphan pass runs. Typically poster_renamerr's destination_dir, but you can list any path you want explicitly cleaned — including source dirs or personal folders that the post-rename pass deliberately leaves alone. Each is walked recursively; the hidden .chub_orphan_restore subdir is skipped.",
            },
            {
                key: 'orphan_instances',
                label: 'Library Instances (Radarr/Sonarr)',
                type: 'instances',
                instance_types: ['radarr', 'sonarr'],
                valueFormat: 'string',
                section: 'Orphan Asset Cleanup',
                description:
                    "Radarr/Sonarr instances whose libraries define which assets are legitimate. An asset is flagged as an orphan only when it matches none of these libraries (by {tmdb-N}/{tvdb-N} id or title). Leave empty to fall back to the Plex Bloat 'Plex Instance(s)' selection above (pre-split behaviour). The comparison set is read from CHUB's media cache, populated by poster_renamerr — run it first if the cache is stale.",
            },
            {
                key: 'include_collections',
                label: 'Include Collections',
                type: 'check_box',
                section: 'Orphan Asset Cleanup',
                description:
                    "Treat Plex collection titles as part of the comparison set so collection posters aren't flagged as orphans. Default on.",
            },
            {
                key: 'orphan_ignore_titles',
                label: 'Ignore Titles',
                type: 'textarea',
                section: 'Orphan Asset Cleanup',
                description:
                    "Titles to never flag as orphans (one per line), even when they don't match a library entry or carry a stale ID tag. Matched on the same normalized key as the scan, so casing/punctuation/year differences are ignored — e.g. 'The Matrix (1999)' and 'the matrix' are equivalent. Useful for personal or manually-placed posters.",
            },
        ],
    },

    {
        key: 'plex_maintenance',
        label: 'Plex Maintenance',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description: 'Set the logging verbosity for Plex maintenance.',
            },
            {
                key: 'plex_path',
                label: 'Plex Path',
                type: 'text',
                required: true,
                description:
                    "Path inside the CHUB container that points at your Plex Media Server's data dir " +
                    '(same value as poster_cleanarr). Required for the PhotoTranscoder cache cleanup.',
            },
            {
                key: 'empty_trash',
                label: 'Empty Trash',
                type: 'check_box',
                description:
                    "Purge Plex's internal trash. Permanently deletes items you've already removed.",
            },
            {
                key: 'clean_bundles',
                label: 'Clean Bundles',
                type: 'check_box',
                description: 'Remove orphaned .bundle folders for media that no longer exists.',
            },
            {
                key: 'optimize_db',
                label: 'Optimize Database',
                type: 'check_box',
                description: "Run VACUUM on Plex's database. Reclaims space, rebuilds indexes.",
            },
            {
                key: 'photo_transcoder',
                label: 'Clear PhotoTranscoder Cache',
                type: 'check_box',
                description: "Clear Plex's transcoded-image cache. Plex regenerates on demand.",
            },
            {
                key: 'sleep',
                label: 'Sleep Between Tasks',
                type: 'number',
                description: 'Seconds to wait between Plex maintenance operations (default: 60).',
            },
            {
                key: 'timeout',
                label: 'Connection Timeout',
                type: 'number',
                description: 'Plex connection timeout in seconds (default: 600).',
            },
            {
                key: 'instances',
                label: 'Plex Instances',
                type: 'instances',
                required: true,
                instance_types: ['plex'],
                valueFormat: 'string',
                description: 'Plex instance to run maintenance tasks against.',
            },
        ],
    },

    {
        key: 'unmatched_assets',
        label: 'Unmatched Assets',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['info', 'debug'],
                required: true,
                description: 'Set the logging verbosity for unmatched asset detection.',
            },
            {
                key: 'ignore_unmonitored',
                label: 'Ignore Unmonitored',
                type: 'check_box',
                description: 'Skip unmonitored media items when scanning for unmatched assets.',
            },
            {
                key: 'instances',
                label: 'Instances',
                type: 'instances',
                required: true,
                add_posters_option: false,
                instance_types: ['radarr', 'sonarr', 'lidarr'],
                // Backend: UnmatchedAssetsConfig.instances is List[str].
                valueFormat: 'string',
                description: 'Instances to scan for unmatched assets.',
            },
            {
                key: 'ignore_folders',
                label: 'Ignore Folders',
                type: 'textarea',
                section: 'Ignore rules',
                description: 'Folder names to skip when scanning (one per line).',
            },
            {
                key: 'ignore_profiles',
                label: 'Ignore Profiles',
                type: 'textarea',
                section: 'Ignore rules',
                description: 'Quality profile names to exclude from scanning (one per line).',
            },
            {
                key: 'ignore_titles',
                label: 'Ignore Titles',
                type: 'textarea',
                section: 'Ignore rules',
                description: 'Media titles to skip when scanning (one per line).',
            },
            {
                key: 'ignore_tags',
                label: 'Ignore Tags',
                type: 'textarea',
                section: 'Ignore rules',
                description: 'Tags to exclude from scanning (one per line).',
            },
            {
                key: 'ignore_collections',
                label: 'Ignore Collections',
                type: 'textarea',
                section: 'Ignore rules',
                description: 'Collection names to exclude from scanning (one per line).',
            },
        ],
    },
];

export const SETTINGS_MODULES = [
    {
        name: 'TMDB',
        key: 'tmdb',
        description:
            'Look up missing TMDB IDs via the TMDB API. Improves poster matching and request links for unmatched assets.',
    },
    {
        name: 'fanart.tv',
        key: 'fanart',
        description:
            'Source logos and backgrounds for Asset Renamerr from fanart.tv, ranked by community likes. Requires your personal fanart.tv API key.',
    },
    {
        name: 'Sync Gdrive',
        key: 'sync_gdrive',
        description: 'Synchronize your Google Drive with CHUB.',
    },
    {
        name: 'Poster Renamerr',
        key: 'poster_renamerr',
        description: 'Automate and configure your poster renaming workflow.',
    },
    {
        name: 'Asset Renamerr',
        key: 'asset_renamerr',
        description:
            'Apply additional artwork — logos, square art, and backgrounds — to Plex or into a Kometa assets directory.',
    },
    {
        name: 'Border Replacerr',
        key: 'border_replacerr',
        description: 'Replace and manage borders for your posters.',
    },
    {
        name: 'Upgradinatorr',
        key: 'upgradinatorr',
        description: 'Send automatic search requests to Radarr/Sonarr/Lidarr instances.',
    },
    {
        name: 'Renameinatorr',
        key: 'renameinatorr',
        description: 'Send rename requests to Sonarr/Radarr instances.',
    },
    {
        name: 'Nohl',
        key: 'nohl',
        description:
            'Find items in your media collection that do not have hardlinks and send requests to Radarr/Sonarr to handle them',
    },
    {
        name: 'Labelarr',
        key: 'labelarr',
        description: 'Sync labels between Radarr/Sonarr -> Plex instances.',
    },
    {
        name: 'Health Checkarr',
        key: 'health_checkarr',
        description: 'Remove Radarr/Sonarr entries that are no longer in sync with TMDb/TVDb',
    },
    { name: 'Jduparr', key: 'jduparr', description: 'Find and handle duplicates in your files.' },
    {
        name: 'Nestarr',
        key: 'nestarr',
        description:
            'Detect unmatched media between ARR and Plex, incorrectly nested folders, and stray or misplaced files in Radarr/Sonarr/Lidarr.',
    },
    {
        name: 'Poster Cleanarr',
        key: 'poster_cleanarr',
        description: 'Clean bloat images from Plex metadata and manage orphaned posters.',
    },
    {
        name: 'Plex Maintenance',
        key: 'plex_maintenance',
        description:
            'Server-level Plex hygiene: empty trash, clean bundles, optimize database, and clear the PhotoTranscoder cache.',
    },
    {
        name: 'Unmatched Assets',
        key: 'unmatched_assets',
        description: 'Handle and review assets that couldn\u2019t be matched.',
    },
];
