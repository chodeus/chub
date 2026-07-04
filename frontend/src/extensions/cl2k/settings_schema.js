// CL2K maker — Module Settings schema fragment.
// Spliced into SETTINGS_SCHEMA / SETTINGS_MODULES by manifest.jsx
// (anchored after border_replacerr, its position before the extension split).

export const CL2K_MAKER_SCHEMA = {
    key: 'cl2k_maker',
    label: 'CL2K Maker',
    // Config-only: posters are generated on-demand from the CL2K Poster Maker
    // page, so there is no batch run. `runnable: false` hides the Run button +
    // Dry-run (ModuleSettingsPage) and drops it from the Schedule and Dashboard.
    runnable: false,
    fields: [
        {
            key: 'log_level',
            label: 'Log Level',
            type: 'dropdown',
            options: ['debug', 'info'],
            required: true,
            description:
                '"debug" prints per-poster art/logo resolution; "info" is the normal cron-friendly level.',
        },
        // ─── Generation ────────────────────────────────────────────
        {
            key: 'skip_existing',
            label: 'Skip Existing',
            type: 'check_box',
            section: 'Generation',
            description:
                'Skip items that already have a generated CL2K poster. The maker page’s force option overrides this per generation.',
        },
        {
            key: 'style',
            label: 'Style Tag',
            type: 'text',
            section: 'Generation',
            placeholder: 'CL2K',
            description: 'poster_cache style tag recorded for generated posters.',
        },
        {
            key: 'priority',
            label: 'Priority',
            type: 'number',
            section: 'Generation',
            placeholder: '0',
            description: 'poster_cache priority for generated posters (higher wins on match).',
        },
        // ─── Save locations (routed cards + coverage, option 2a) ──
        // Custom field types registered by manifest.jsx from
        // SaveLocationsFields.jsx; each card renders its own description, add
        // button, entry list and empty state. Nothing here is required — zero
        // locations is valid (unrouted art stays downloadable from the maker
        // page).
        {
            key: 'local_folders',
            label: 'Local Folders',
            type: 'cl2k_local_folders',
            section: 'Local Folders',
            required: false,
        },
        {
            key: 'gdrive_uploads',
            label: 'Google Drives',
            type: 'cl2k_gdrive_uploads',
            section: 'Google Drives',
            required: false,
        },
        {
            // Read-only, live-computed strip — carries no config value of its
            // own (never calls onChange, so the key never lands in formData).
            key: 'save_coverage',
            label: 'Coverage',
            type: 'cl2k_coverage',
            section: 'Coverage',
            required: false,
        },
        // ─── Logo & text ───────────────────────────────────────────
        {
            key: 'whiten_logo',
            label: 'Whiten Logo',
            type: 'check_box',
            section: 'Logo & Text',
            description: 'Recolor the clear logo to solid white (the CL2K look).',
        },
        {
            key: 'text_logo_fallback',
            label: 'Text Logo Fallback',
            type: 'check_box',
            section: 'Logo & Text',
            description:
                'When no clear logo is found on TMDB or fanart.tv, synthesize an ALL-CAPS typeset wordmark from the title. Long titles are balance-wrapped onto two/three lines to fill the logo box.',
        },
        {
            key: 'text_logo_stroke',
            label: 'Text Logo Outline (px)',
            type: 'number',
            section: 'Logo & Text',
            placeholder: '0',
            description:
                'Outline width for the synthesized text wordmark; 0 = none (clean white, the CL2K default). A small value (~4) adds legibility over busy artwork.',
        },
        {
            key: 'language',
            label: 'Language',
            type: 'text',
            section: 'Logo & Text',
            placeholder: 'en',
            description: 'ISO-639-1 language preferred for logo selection.',
        },
        // ─── AI text removal ───────────────────────────────────────
        {
            key: 'ai_provider',
            label: 'AI Provider',
            type: 'dropdown',
            options: ['none', 'lama_sidecar', 'openai'],
            section: 'AI Text Removal',
            required: true,
            description:
                'Inpainter used when "Remove text" is enabled with a brushed mask. "none" disables it; "lama_sidecar" is free/local; "openai" is paid.',
        },
        {
            // Only the LaMa sidecar uses an endpoint URL; OpenAI's endpoint is
            // built in, so this is hidden for openai/none.
            key: 'ai_endpoint',
            label: 'AI Endpoint',
            type: 'text',
            section: 'AI Text Removal',
            conditional: {
                field: 'ai_provider',
                condition: 'in',
                value: ['lama_sidecar'],
            },
            placeholder: 'http://<host>:8418',
            description:
                'Just your lama-sidecar container’s address — http://<host>:<port>, where <port> is the sidecar container’s mapped port (not CHUB’s). CHUB adds the /api/v1/... paths for you.',
        },
        {
            key: 'api_key',
            label: 'AI API Key',
            type: 'password',
            section: 'AI Text Removal',
            conditional: {
                field: 'ai_provider',
                condition: 'in',
                value: ['openai', 'lama_sidecar'],
            },
            description:
                'OpenAI token. For the LaMa sidecar this is optional: set it only if the sidecar runs with LAMA_API_KEY (sent as X-API-Key).',
        },
        {
            key: 'ai_model',
            label: 'AI Model',
            type: 'text',
            section: 'AI Text Removal',
            conditional: {
                field: 'ai_provider',
                condition: 'in',
                value: ['openai'],
            },
            description: 'OpenAI model id (default gpt-image-1).',
        },
        {
            key: 'ai_prompt',
            label: 'AI Prompt',
            type: 'textarea',
            section: 'AI Text Removal',
            conditional: {
                field: 'ai_provider',
                condition: 'in',
                value: ['openai'],
            },
            description: 'Prompt sent to OpenAI when removing text.',
        },
        {
            key: 'ai_mask_dilate',
            label: 'Mask Dilation (px)',
            type: 'number',
            section: 'AI Text Removal',
            conditional: {
                field: 'ai_provider',
                condition: 'in',
                value: ['lama_sidecar'],
            },
            placeholder: '-1',
            description:
                'How far the sidecar grows your brush strokes before erasing, so a logo’s anti-aliased fringe/glow goes too. -1 uses the sidecar’s default (5). Raise to 7–8 for glowing/beveled logos if a faint outline survives; lower to 2–3 if you brush generously.',
        },
        {
            key: 'ai_logo_upscale',
            label: 'Upscale Small Logos',
            type: 'check_box',
            section: 'AI Text Removal',
            conditional: {
                field: 'ai_provider',
                condition: 'in',
                value: ['lama_sidecar'],
            },
            description:
                'When an auto-sourced clear logo is too small for the poster’s logo box, upscale it 2–4x on the sidecar (Real-ESRGAN) instead of falling back to a plain text wordmark. Any sidecar failure quietly falls back to the old behaviour.',
        },
        {
            key: 'ai_timeout',
            label: 'AI Timeout (s)',
            type: 'number',
            section: 'AI Text Removal',
            conditional: {
                field: 'ai_provider',
                condition: 'not_equals',
                value: 'none',
            },
            placeholder: '120',
            description: 'Seconds to wait for the AI provider before giving up.',
        },
    ],
};

export const CL2K_MAKER_MODULE_ENTRY = {
    name: 'CL2K Maker',
    key: 'cl2k_maker',
    description:
        'Generate DAPS-named CL2K posters from TMDB/fanart art, .psd sources, or uploads. Build posters on the CL2K Poster Maker page.',
};
