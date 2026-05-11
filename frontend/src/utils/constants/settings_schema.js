// web/static/js/settings/settings_schema.js
export const SETTINGS_SCHEMA = [
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
                key: 'client_id',
                label: 'Client ID',
                type: 'password',
                required: false,
                placeholder: 'Place Client ID Here',
                description: 'Google API client ID for authentication.',
            },
            {
                key: 'client_secret',
                label: 'Client Secret',
                type: 'password',
                required: false,
                description: 'Google API client secret for authentication.',
            },
            {
                key: 'token',
                label: 'Token (JSON)',
                type: 'json',
                required: false,
                placeholder:
                    '{\n  "access_token": "ya29.a0AfH6SMBEXAMPLEEXAMPLETOKEN",\n  "refresh_token": "1",\n  "scope": "https://www.googleapis.com/auth/drive",\n  "token_type": "Bearer",\n  "expiry_date": 1712345678901\n}',
                description: 'OAuth2 token JSON for authenticating with Google Drive.',
            },
            {
                key: 'gdrive_sa_location',
                label: 'Service Account Location',
                type: 'text',
                required: false,
                description: 'Path to the Google Drive service account credentials file.',
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
                        presetUrl:
                            'https://raw.githubusercontent.com/Drazzilb08/daps-gdrive-presets/CL2K/presets.json',
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
            // ─── Source ────────────────────────────────────────────────
            {
                key: 'source_dirs',
                label: 'Source Directories',
                type: 'dirlist_dragdrop',
                section: 'Source',
                required: true,
                description:
                    'Folders scanned for poster assets. Drag to set priority — earlier directories win when multiple sources have a poster for the same item.',
            },
            {
                key: 'sync_posters',
                label: 'Sync from Google Drive first',
                type: 'check_box',
                section: 'Source',
                description:
                    'Run Sync Gdrive before each Poster Renamerr run so the source directories are up to date. Requires Sync Gdrive to be configured.',
            },
            // ─── Output ────────────────────────────────────────────────
            {
                key: 'destination_dir',
                label: 'Destination Directory',
                type: 'dir',
                section: 'Output',
                required: true,
                description:
                    'Where renamed posters are written. Plex/Kometa-compatible asset folder structure when "Asset folders" is enabled below.',
            },
            {
                key: 'action_type',
                label: 'File Action',
                type: 'dropdown',
                section: 'Output',
                options: ['copy', 'move', 'hardlink', 'symlink'],
                required: true,
                description:
                    'How matched posters reach the destination. "hardlink" is fastest and saves disk space when source and destination are on the same filesystem; "copy" is safest if you are unsure.',
            },
            {
                key: 'asset_folders',
                label: 'Asset folders (per-show)',
                type: 'check_box',
                section: 'Output',
                description:
                    'Enable Plex-style folder layout: destination/<Show Name>/poster.jpg + Season01.jpg. When off, files are flat: destination/<Show Name>_Season01.jpg.',
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
                key: 'run_cleanarr',
                label: 'Run Poster Cleanarr after rename',
                type: 'check_box',
                section: 'Pipeline',
                description:
                    'After renaming, sweep the destination for orphaned posters whose media no longer exists in Radarr/Sonarr/Plex. Configure scope in the Poster Cleanarr module.',
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
            // ─── Operation ─────────────────────────────────────────────
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                section: 'Operation',
                options: ['debug', 'info'],
                required: true,
                description:
                    '"debug" prints per-file decisions and is useful when investigating a missing match; "info" is the normal cron-friendly level.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                section: 'Operation',
                description:
                    'Walk the full pipeline and log every action that would be taken — but write nothing to disk and upload nothing to Plex.',
            },
            {
                key: 'print_only_renames',
                label: 'Log only renamed files',
                type: 'check_box',
                section: 'Operation',
                description:
                    'Quiet the log by suppressing entries for files that are already up to date. Only newly renamed/copied files are logged.',
            },
        ],
    },

    {
        key: 'border_replacerr',
        label: 'Border Replacerr',
        fields: [
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
                type: 'color_list_poster',
                section: 'Border',
                preview: 'true',
                description:
                    'Colors used to repaint the border once cropped. With one or more colors set, the existing border is replaced by the selected color (cycling per poster if multiple). With no colors set, the border is simply stripped — the poster keeps its cropped artwork at 1000×1500 with no replacement border.',
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
                    "Per-holiday color overrides. When today falls inside a holiday's schedule, that holiday's colors are used instead of the default Border Colors above.",
                fields: [
                    {
                        key: 'preset',
                        label: 'Holiday Presets',
                        type: 'presets',
                        presetType: 'holiday',
                        identifierField: 'name',
                        moduleConfigKey: 'holidays',
                        targetFields: ['name', 'schedule', 'colors'],
                        description: 'Select a preset for holiday color overrides.',
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
                    {
                        key: 'colors',
                        label: 'Colors',
                        type: 'color_list',
                        preview: 'false',
                        required: false,
                        description: 'Colors to use for the holiday border override.',
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
            // ─── Operation ─────────────────────────────────────────────
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                section: 'Operation',
                options: ['debug', 'info'],
                required: true,
                description:
                    '"debug" prints per-poster crop/replace decisions; "info" is the normal cron-friendly level.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                section: 'Operation',
                description:
                    'Walk the full pipeline and log every poster that would be re-bordered — but write nothing to disk.',
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
                            'Temporarily opt this profile out without deleting its settings.',
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

                description: 'Mappings of app_type, app_instance, labels, plex_instances.',
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
                description: 'Simulate health checks without making changes.',
            },
            {
                key: 'report_only',
                label: 'Report Only',
                type: 'check_box',
                description: 'Report removed TMDB/TVDB entries without deleting them.',
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
                    'Map Plex libraries to ARR instances for comparison. Only mapped libraries are checked — unmapped libraries (e.g. Music) are excluded. Leave empty to compare everything.',
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
                description:
                    'Operation mode: report (dry run), move (recoverable), remove (permanent), restore (recover moved), clear (delete restore dir), nothing (skip images).',
            },
            {
                key: 'plex_path',
                label: 'Plex Path',
                type: 'text',
                required: true,
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
                description:
                    'Copy the Plex database locally instead of downloading via API. Requires Plex to be stopped.',
            },
            {
                key: 'use_existing_db',
                label: 'Use Existing Database',
                type: 'check_box',
                description: 'Reuse existing database copy if less than 2 hours old.',
            },
            {
                key: 'ignore_running',
                label: 'Ignore Running Check',
                type: 'check_box',
                description: 'Bypass the Plex running detection when using local database mode.',
            },
            {
                key: 'overlays_only',
                label: 'Overlays Only',
                type: 'check_box',
                description:
                    'Only act on files that carry the Kometa overlay EXIF tag. Custom-uploaded posters/art (which lack the tag) are left alone. Safer for Kometa users — files without the marker are skipped, not deleted.',
            },
            {
                key: 'sleep',
                label: 'Sleep Between Operations',
                type: 'number',
                description: 'Seconds to wait between operations (default: 60).',
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
                description: 'Plex instance used to retrieve the library database.',
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
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description: 'Report unmatched assets without making changes.',
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
                description: 'Folder names to skip when scanning (one per line).',
            },
            {
                key: 'ignore_profiles',
                label: 'Ignore Profiles',
                type: 'textarea',
                description: 'Quality profile names to exclude from scanning (one per line).',
            },
            {
                key: 'ignore_titles',
                label: 'Ignore Titles',
                type: 'textarea',
                description: 'Media titles to skip when scanning (one per line).',
            },
            {
                key: 'ignore_tags',
                label: 'Ignore Tags',
                type: 'textarea',
                description: 'Tags to exclude from scanning (one per line).',
            },
            {
                key: 'ignore_collections',
                label: 'Ignore Collections',
                type: 'textarea',
                description: 'Collection names to exclude from scanning (one per line).',
            },
        ],
    },
    {
        key: 'general',
        label: 'General',
        fields: [
            {
                key: 'duplicate_exclude_groups',
                label: 'Quality Instance Groups',
                type: 'object_array',
                description:
                    'Group instances that intentionally share the same content at different qualities (e.g. radarr + radarr4k). Items found across instances within the same group will not be flagged as duplicates.',
                fields: [
                    {
                        key: 'instances',
                        label: 'Instances',
                        type: 'tag_input',
                        required: true,
                        allowCustom: true,
                        placeholder: 'Type instance name and press Enter...',
                        description:
                            'Enter the names of 2 or more instances that share content (e.g. radarr, radarr4k).',
                    },
                ],
            },
        ],
    },
];

export const SETTINGS_MODULES = [
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
        description: 'Detect and fix incorrectly nested media folders in Radarr/Sonarr/Lidarr.',
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
    {
        name: 'General',
        key: 'general',
        description: 'General application settings including duplicate detection and logging.',
    },
];
