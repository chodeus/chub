// CL2K maker — Module Settings schema fragment.
// Spliced into SETTINGS_SCHEMA / SETTINGS_MODULES by manifest.jsx
// (anchored after border_replacerr, its position before the extension split).

export const CL2K_MAKER_SCHEMA = {
    key: 'cl2k_maker',
    label: 'CL2K Maker',
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
        {
            key: 'enabled',
            label: 'Enabled',
            type: 'check_box',
            description:
                'Enable the scheduled batch run (walks matched movies/shows lacking a CL2K poster). On-demand generation from the CL2K Poster Maker page works regardless.',
        },
        // ─── Output ────────────────────────────────────────────────
        {
            key: 'output_dir',
            label: 'Output Directory',
            type: 'dir',
            section: 'Output',
            required: true,
            description:
                'Where generated CL2K posters are written. Make this one of Poster Renamerr’s source directories so the rest of CHUB picks them up.',
        },
        {
            key: 'skip_existing',
            label: 'Skip Existing',
            type: 'check_box',
            section: 'Output',
            description:
                'Skip items that already have a generated CL2K poster (the duplicate guard). The page’s force option overrides this per generation.',
        },
        {
            key: 'style',
            label: 'Style Tag',
            type: 'text',
            section: 'Output',
            placeholder: 'CL2K',
            description: 'poster_cache style tag recorded for generated posters.',
        },
        {
            key: 'priority',
            label: 'Priority',
            type: 'number',
            section: 'Output',
            placeholder: '0',
            description: 'poster_cache priority for generated posters (higher wins on match).',
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
        // ─── Google Drive upload ───────────────────────────────────
        {
            key: 'upload_to_gdrive',
            label: 'Upload to Google Drive',
            type: 'check_box',
            section: 'Google Drive Upload',
            description:
                'After saving, copy the generated poster to a Drive folder via rclone. Uploads use your Sync GDrive OAuth token — set one under Sync GDrive (a service account can’t own files in a personal Drive, so it has no usable upload path).',
        },
        {
            key: 'gdrive_folder_id',
            label: 'Upload Folder ID',
            type: 'text',
            section: 'Google Drive Upload',
            description:
                'Destination Google Drive folder ID for uploads. The folder is written to as you (via the Sync GDrive OAuth token), so the posters are owned by you.',
        },
        // ─── AI text removal ───────────────────────────────────────
        {
            key: 'ai_provider',
            label: 'AI Provider',
            type: 'dropdown',
            options: ['none', 'lama_sidecar', 'openai', 'huggingface'],
            section: 'AI Text Removal',
            required: true,
            description:
                'Inpainter used when "Remove text" is enabled with a brushed mask. "none" disables it; "lama_sidecar" is free/local; "openai" is paid; "huggingface" is a rate-limited free tier.',
        },
        {
            // Only LaMa sidecar / Hugging Face use an endpoint URL; OpenAI's
            // endpoint is built in, so this is hidden for openai/none.
            key: 'ai_endpoint',
            label: 'AI Endpoint',
            type: 'text',
            section: 'AI Text Removal',
            conditional: {
                field: 'ai_provider',
                condition: 'in',
                value: ['lama_sidecar', 'huggingface'],
            },
            placeholder: 'http://<host>:8080/api/v1/inpaint',
            description:
                'The full URL CHUB sends the image to. LaMa (IOPaint): your sidecar container’s address including the path — http://<host>:<port>/api/v1/inpaint — where <port> is the IOPaint container’s mapped port (not CHUB’s). Hugging Face: the model inference URL.',
        },
        {
            key: 'ai_api_key',
            label: 'AI API Key',
            type: 'password',
            section: 'AI Text Removal',
            conditional: {
                field: 'ai_provider',
                condition: 'in',
                value: ['openai', 'huggingface'],
            },
            description: 'OpenAI / Hugging Face token. (LaMa sidecar needs no key.)',
        },
        {
            key: 'ai_model',
            label: 'AI Model',
            type: 'text',
            section: 'AI Text Removal',
            conditional: {
                field: 'ai_provider',
                condition: 'in',
                value: ['openai', 'huggingface'],
            },
            description: 'OpenAI model id (default gpt-image-1) or Hugging Face model id.',
        },
        {
            key: 'ai_prompt',
            label: 'AI Prompt',
            type: 'textarea',
            section: 'AI Text Removal',
            conditional: {
                field: 'ai_provider',
                condition: 'in',
                value: ['openai', 'huggingface'],
            },
            description: 'Prompt sent to OpenAI / Hugging Face when removing text.',
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
        'Generate DAPS-named CL2K posters from TMDB/fanart art, .psd sources, or uploads. Configure output, logo, AI text-removal, and .psd source drives here; build posters on the CL2K Poster Maker page.',
};
