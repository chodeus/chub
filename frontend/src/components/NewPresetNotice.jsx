import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { Button, LoadingButton } from './ui';
import { dismissNewGdrivePresets, fetchNewGdrivePresets } from '../utils/gdrivePresets.js';

const SYNC_GDRIVE_SETTINGS = '/settings/modules/sync_gdrive';

/**
 * Corner card listing GDrive presets that arrived in a CHUB update. Dismiss
 * clears them for good; Open hides the card until the next app load.
 */
const NewPresetNotice = () => {
    const navigate = useNavigate();
    const [presets, setPresets] = useState([]);
    const [hidden, setHidden] = useState(false);
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        let mounted = true;
        fetchNewGdrivePresets()
            .then(list => mounted && setPresets(list))
            // Optional hint: a failed check just shows nothing
            .catch(err => console.warn('[NewPresetNotice] check failed:', err));
        return () => {
            mounted = false;
        };
    }, []);

    const dismiss = useCallback(async () => {
        setBusy(true);
        try {
            await dismissNewGdrivePresets(presets.map(p => p.id));
            setPresets([]);
        } catch (err) {
            console.warn('[NewPresetNotice] dismiss failed:', err);
        } finally {
            setBusy(false);
        }
    }, [presets]);

    const open = useCallback(() => {
        setHidden(true);
        navigate(SYNC_GDRIVE_SETTINGS);
    }, [navigate]);

    if (hidden || presets.length === 0) return null;

    const title =
        presets.length === 1 ? 'New GDrive preset' : `${presets.length} new GDrive presets`;

    return (
        <section
            aria-label={title}
            className="fixed bottom-4 right-4 z-fixed w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-surface-elevated p-4 shadow-lg"
        >
            <h2 className="mb-1 font-display text-heading font-semibold text-fg">{title}</h2>
            <div className="mb-2 text-xs text-fg-subtle">
                Added in a CHUB update. Add the ones you want in Sync GDrive.
            </div>
            <ul className="mb-3 space-y-1 text-sm text-fg-muted">
                {presets.map(p => (
                    <li key={p.id} className="truncate">
                        {p.name}
                    </li>
                ))}
            </ul>
            <div className="flex gap-2">
                <Button size="small" onClick={open}>
                    Open Sync GDrive
                </Button>
                <LoadingButton
                    size="small"
                    variant="ghost"
                    onClick={dismiss}
                    loading={busy}
                    loadingText="Dismissing…"
                >
                    Dismiss
                </LoadingButton>
            </div>
        </section>
    );
};

export default NewPresetNotice;
