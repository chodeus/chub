import React from 'react';
import { Button, LoadingButton } from '../../components/ui/index.js';

// `confirm`: Run opens a confirmation modal (permanent operations only).
// `passes`: the mode runs the Bloat/Stale/Orphan passes, and a selection scopes its Bloat pass.
export const MODE_META = {
    report: {
        label: 'Report',
        action: 'Run scan',
        variant: 'primary',
        confirm: false,
        description: 'List bloat images in the UI. Nothing is deleted.',
    },
    move: {
        label: 'Move',
        action: 'Move bloat to restore',
        variant: 'warning',
        confirm: false,
        passes: true,
        description: 'Relocate bloat to <plex_path>/Poster Cleanarr Restore/ — recoverable.',
    },
    restore: {
        label: 'Restore',
        action: 'Restore files',
        variant: 'success',
        confirm: false,
        description: 'Move everything in the Restore directory back to Metadata/.',
    },
    clear: {
        label: 'Clear',
        action: 'Clear restore dir',
        variant: 'danger',
        confirm: true,
        description: 'Permanently delete everything in the Restore directory. Cannot be undone.',
    },
    remove: {
        label: 'Remove',
        action: 'Delete bloat permanently',
        variant: 'danger',
        confirm: true,
        passes: true,
        description: 'Delete bloat from disk directly. Cannot be undone.',
    },
    nothing: {
        label: 'Nothing',
        action: null,
        variant: 'secondary',
        confirm: false,
        description:
            'Skip image processing entirely. Useful for scheduling an orphan-cleanup-only run.',
    },
};

// Off and unclickable while the mode runs no passes.
const ModeCheck = ({ label, active, checked, locked = false, onChange, title }) => {
    const disabled = !active || locked;
    const on = active && checked;
    return (
        <button
            type="button"
            disabled={disabled}
            onClick={() => onChange(!checked)}
            title={title}
            className={`flex items-center gap-2 text-dense text-fg ${
                disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'
            }`}
        >
            <span
                className={`flex items-center justify-center w-[17px] h-[17px] rounded-[4px] border transition-colors ${
                    on ? 'bg-primary border-primary' : 'bg-transparent border-border-strong'
                }`}
            >
                {on && (
                    <span className="material-symbols-outlined text-on-color text-[13px] leading-none">
                        check
                    </span>
                )}
            </span>
            {label}
        </button>
    );
};

const SelectionNote = ({ count, onClear }) => (
    <>
        <span className="text-xs text-fg-muted">
            {count > 0 ? `${count} selected` : 'No selection → full library'}
        </span>
        {count > 0 && (
            <Button variant="ghost" onClick={onClear}>
                Clear
            </Button>
        )}
    </>
);

const CleanarrModeBar = ({
    mode,
    onModeChange,
    bloat,
    onBloatChange,
    stale,
    onStaleChange,
    orphan,
    onOrphanChange,
    overlaysOnly,
    onOverlaysOnlyChange,
    selectedCount,
    onClearSelection,
    scanning,
    enqueuing,
    hasScanned,
    onRun,
}) => {
    const meta = MODE_META[mode];
    const passesOn = Boolean(meta?.passes);
    const report = mode === 'report';
    return (
        <section
            className="rounded-xl bg-surface border border-border px-4 py-3.5 flex flex-wrap items-center gap-4"
            style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
        >
            <label className="flex items-center gap-2 text-dense font-semibold text-fg-muted">
                Mode
                <select
                    value={mode}
                    onChange={e => onModeChange(e.target.value)}
                    className="h-11 bg-surface-inset border border-border rounded-lg px-3 text-dense font-semibold text-fg outline-none focus:border-primary cursor-pointer"
                >
                    {Object.entries(MODE_META).map(([k, m]) => (
                        <option key={k} value={k}>
                            {m.label}
                        </option>
                    ))}
                </select>
            </label>
            <span className="text-dense text-fg-subtle" style={{ maxWidth: '420px' }}>
                {meta?.description}
            </span>
            <div className="flex flex-wrap items-center gap-4">
                <ModeCheck
                    label="Bloat"
                    active={passesOn}
                    checked={bloat}
                    onChange={onBloatChange}
                />
                <ModeCheck
                    label="Stale"
                    active={passesOn}
                    checked={stale}
                    onChange={onStaleChange}
                />
                <ModeCheck
                    label="Orphan"
                    active={passesOn}
                    checked={orphan}
                    onChange={onOrphanChange}
                />
                <ModeCheck
                    label="Overlays only"
                    active={passesOn}
                    checked={overlaysOnly}
                    locked={!bloat}
                    onChange={onOverlaysOnlyChange}
                    title="Limit the bloat pass to Kometa overlay images (EXIF-tagged), sparing user-uploaded customs"
                />
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-2">
                {passesOn && <SelectionNote count={selectedCount} onClear={onClearSelection} />}
                <LoadingButton
                    loading={report ? scanning : enqueuing}
                    loadingText={report ? 'Scanning…' : 'Starting…'}
                    variant={meta?.variant || 'primary'}
                    onClick={onRun}
                    disabled={
                        !meta?.action ||
                        (passesOn && !hasScanned) ||
                        (passesOn && !bloat && !stale && !orphan)
                    }
                >
                    {meta?.action || 'No action'}
                </LoadingButton>
            </div>
        </section>
    );
};

export default CleanarrModeBar;
