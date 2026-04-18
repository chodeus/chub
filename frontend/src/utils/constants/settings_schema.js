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
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description: 'Set the logging verbosity for poster renaming.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description: 'Simulate actions without making changes.',
            },
            {
                key: 'sync_posters',
                label: 'Sync Posters',
                type: 'check_box',
                description: 'Enable to run Sync Gdrive prior to running Poster Renamerr',
            },
            {
                key: 'action_type',
                label: 'Action Type',
                type: 'dropdown',
                options: ['copy', 'move', 'hardlink', 'symlink'],
                required: true,
                description: 'Select the file operation to use for renaming posters.',
            },
            {
                key: 'asset_folders',
                label: 'Asset Folders',
                type: 'check_box',
                description: 'Enable to use asset folders for organizing posters.',
            },
            {
                key: 'print_only_renames',
                label: 'Print Only Renames',
                type: 'check_box',
                description: 'Only print renaming actions without performing them.',
            },
            {
                key: 'run_border_replacerr',
                label: 'Run Border Replacerr',
                type: 'check_box',
                description: 'Enable automatic border replacement during renaming.',
            },
            {
                key: 'incremental_border_replacerr',
                label: 'Incremental Border Replacerr',
                type: 'check_box',
                description: 'Run border replacerr incrementally with each operation.',
            },
            {
                key: 'run_cleanarr',
                label: 'Run Cleanarr',
                type: 'check_box',
                description: 'Enable to run Cleanarr after renaming.',
            },
            {
                key: 'report_unmatched_assets',
                label: 'Report Unmatched Assets',
                type: 'check_box',
                description: 'Report assets that could not be matched during renaming.',
            },
            {
                key: 'source_dirs',
                label: 'Source Directories',
                type: 'dirlist_dragdrop',
                required: true,

                description: 'Directories to scan for posters to rename.',
            },
            {
                key: 'destination_dir',
                label: 'Destination Directory',
                type: 'dir',
                required: true,

                description: 'Directory where renamed posters are placed.',
            },
            {
                key: 'instances',
                label: 'Instances',
                type: 'instances',
                required: true,
                add_posters_option: true,
                instance_types: ['plex', 'radarr', 'sonarr', 'lidarr'],
                description:
                    'List of Plex/Radarr/Sonarr/Lidarr instances to pull renaming data from.',
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
                description: 'Set the logging verbosity for border replacerr.',
            },
            {
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description: 'Simulate border replacement without making changes.',
            },
            {
                key: 'border_width',
                label: 'Border Width (px)',
                type: 'number',
                required: true,
                placeholder: '26px',
                description: 'Width of the border to apply to posters, in pixels.',
            },
            {
                key: 'skip',
                label: 'Skip',
                type: 'check_box',
                description: 'Skip replacing/updating borders for posters until holidays.',
            },
            {
                key: 'exclusion_list',
                label: 'Exclusion List',
                type: 'textarea',
                description: 'List of items to exclude from border replacement.',
            },
            {
                key: 'border_colors',
                label: 'Border Colors',
                type: 'color_list_poster',
                preview: 'true',
                description: 'List of colors to use for poster borders.',
            },
            {
                key: 'holidays',
                label: 'Holidays',
                type: 'object_array',
                displayType: 'replacerr',

                description: 'Add holiday color overrides.',
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

                description: 'List of instance configs.',
                fields: [
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
                        key: 'search_mode',
                        label: 'Search Mode',
                        type: 'dropdown',
                        options: ['upgrade', 'missing', 'cutoff'],
                        required: false,
                        description:
                            'Upgrade: search all untagged items for better quality. Missing: search only items with no files. Cutoff: search items below quality profile cutoff.',
                    },
                    {
                        key: 'count',
                        label: 'Count',
                        type: 'number',
                        required: true,
                        description: 'Number of items to upgrade per run.',
                    },
                    {
                        key: 'tag_name',
                        label: 'Tag Name',
                        type: 'text',
                        required: true,
                        description: 'Tag name to filter items for upgrade.',
                    },
                    {
                        key: 'ignore_tag',
                        label: 'Ignore Tag',
                        type: 'text',
                        description: 'Tag name to exclude from upgrade.',
                    },
                    {
                        key: 'unattended',
                        label: 'Unattended',
                        type: 'check_box',
                        description: 'Run upgrades without user intervention.',
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
                key: 'instances',
                label: 'Instances',
                type: 'instances',
                required: true,
                add_posters_option: false,
                instance_types: ['radarr', 'sonarr'],
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

                description: 'Directories to scan for duplicate files.',
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
                key: 'dry_run',
                label: 'Dry Run',
                type: 'check_box',
                description: 'Report nested media without making changes.',
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
                description: 'Path to your Plex Media Server configuration directory.',
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
                key: 'photo_transcoder',
                label: 'Clean PhotoTranscoder',
                type: 'check_box',
                description: 'Delete cached transcoded images from the PhotoTranscoder directory.',
            },
            {
                key: 'empty_trash',
                label: 'Empty Trash',
                type: 'check_box',
                description: 'Run Plex Empty Trash after cleanup.',
            },
            {
                key: 'clean_bundles',
                label: 'Clean Bundles',
                type: 'check_box',
                description: 'Run Plex Clean Bundles after cleanup.',
            },
            {
                key: 'optimize_db',
                label: 'Optimize Database',
                type: 'check_box',
                description: 'Run Plex Optimize Database after cleanup.',
            },
            {
                key: 'sleep',
                label: 'Sleep Between Operations',
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
                description: 'Plex instance to use for database download and maintenance tasks.',
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
        description:
            'Clean bloat images from Plex metadata, manage orphaned posters, and run Plex maintenance tasks.',
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
