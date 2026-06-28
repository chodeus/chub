// poster_self_heal — Module Settings schema fragment.
// Spliced into SETTINGS_SCHEMA / SETTINGS_MODULES by manifest.jsx.
// Runnable (no runnable:false): it runs on a schedule to detect drift.

export const POSTER_SELF_HEAL_SCHEMA = {
    key: 'poster_self_heal',
    label: 'Poster Healer',
    fields: [
        {
            key: 'log_level',
            label: 'Log Level',
            type: 'dropdown',
            options: ['debug', 'info'],
            required: true,
            description:
                '"debug" logs every poster’s resolution; "info" is the normal cron-friendly level.',
        },
        {
            key: 'backfill_ids',
            label: 'Backfill missing IDs',
            type: 'check_box',
            description:
                'Also ADD resolved {tmdb-…}/{tvdb-…}/{imdb-…} ids to a poster that has none — not just correct posters that already carry an id. The source drive (CL2K output dir + Google Drive folder) comes from the CL2K Maker settings.',
        },
        {
            key: 'auto_apply',
            label: 'Auto-apply confident fixes',
            type: 'check_box',
            description:
                'Apply confident fixes automatically during the run (rename on Google Drive + locally) instead of waiting for manual review. Ambiguous matches — where a title matches more than one library item — always go to the review page regardless.',
        },
    ],
};

export const POSTER_SELF_HEAL_MODULE_ENTRY = {
    name: 'Poster Healer',
    key: 'poster_self_heal',
    description:
        'Keep your CL2K poster drive current — re-resolve each generated poster against TMDB and propose fixing stale ids, titles, and years, applied after manual review.',
};
