import React, { useCallback } from 'react';
import { ScheduleField } from '../fields/custom/ScheduleField';
import { Button } from '../ui';

// Editor for a module's multi-block schedules. Each block fires on its own
// schedule and applies its own overrides to that run (e.g. a daily "report"
// block plus a weekly "remove" block). `mode` is broken out as a dropdown
// since it's the primary override; everything else lives in an advanced JSON
// field. Blocks run alongside the module's single top-level schedule.

// Mode values shared by the cleanup-style modules. Other modules ignore an
// unknown mode, so offering the superset is harmless.
const MODE_OPTIONS = ['', 'report', 'move', 'remove', 'nothing', 'restore', 'clear'];

let _bid = 0;
const nextId = () => `blk_${(_bid += 1)}`;
const emptyBlock = () => ({
    _id: nextId(),
    label: '',
    enabled: true,
    schedule: '',
    mode: '',
    extra: '',
});

// Split stored override objects into the mode field + advanced JSON (the rest),
// for editing. Adds a stable _id so list keys survive add/remove.
export const blocksFromConfig = (raw = []) =>
    (raw || []).map(b => {
        const ov = b.overrides || {};
        const { mode, ...rest } = ov;
        return {
            _id: nextId(),
            label: b.label || '',
            enabled: b.enabled !== false,
            schedule: b.schedule || '',
            mode: mode || '',
            extra: Object.keys(rest).length ? JSON.stringify(rest) : '',
        };
    });

// Rebuild the API payload. Throws on invalid advanced JSON so the caller can
// surface a toast and keep the modal open.
export const blocksToConfig = blocks =>
    blocks.map((b, i) => {
        let extra = {};
        const trimmed = (b.extra || '').trim();
        if (trimmed) {
            try {
                extra = JSON.parse(trimmed);
            } catch {
                throw new Error(`Block ${i + 1}: advanced overrides is not valid JSON`);
            }
            if (extra === null || typeof extra !== 'object' || Array.isArray(extra)) {
                throw new Error(`Block ${i + 1}: advanced overrides must be a JSON object`);
            }
        }
        const overrides = { ...extra, ...(b.mode ? { mode: b.mode } : {}) };
        return {
            label: b.label || '',
            enabled: b.enabled !== false,
            schedule: b.schedule || '',
            overrides,
        };
    });

export const ScheduleBlocksEditor = ({ blocks, onChange, disabled }) => {
    const update = useCallback(
        (idx, patch) => {
            onChange(blocks.map((b, i) => (i === idx ? { ...b, ...patch } : b)));
        },
        [blocks, onChange]
    );
    const add = useCallback(() => onChange([...blocks, emptyBlock()]), [blocks, onChange]);
    const remove = useCallback(
        idx => onChange(blocks.filter((_, i) => i !== idx)),
        [blocks, onChange]
    );

    return (
        <div className="flex flex-col gap-3 mt-4 pt-4 border-t border-border">
            <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-fg">Schedule blocks</span>
                <span className="text-xs text-fg-subtle">
                    Extra schedules, each with its own overrides — e.g. a daily{' '}
                    <span className="text-fg-muted">report</span> plus a weekly{' '}
                    <span className="text-fg-muted">remove</span>.
                </span>
            </div>

            {blocks.map((b, i) => (
                <div
                    key={b._id}
                    className="rounded-lg border border-border bg-surface-alt p-3 flex flex-col gap-2"
                >
                    <div className="flex items-center gap-2">
                        <input
                            type="text"
                            value={b.label}
                            disabled={disabled}
                            onChange={e => update(i, { label: e.target.value })}
                            placeholder={`Block ${i + 1} label`}
                            className="flex-1 px-2 py-1 rounded bg-surface border border-border text-sm"
                        />
                        <label className="flex items-center gap-1 text-xs cursor-pointer">
                            <input
                                type="checkbox"
                                checked={b.enabled}
                                disabled={disabled}
                                onChange={e => update(i, { enabled: e.target.checked })}
                            />
                            Enabled
                        </label>
                        <Button variant="ghost" onClick={() => remove(i)} disabled={disabled}>
                            Remove
                        </Button>
                    </div>

                    <ScheduleField
                        field={{ key: `block-${i}-schedule`, label: 'Schedule', required: false }}
                        value={b.schedule}
                        onChange={v => update(i, { schedule: v })}
                        disabled={disabled}
                    />

                    <label className="flex items-center gap-2 text-sm">
                        Mode override:
                        <select
                            value={b.mode}
                            disabled={disabled}
                            onChange={e => update(i, { mode: e.target.value })}
                            className="bg-surface border border-border rounded px-2 py-1 text-sm"
                        >
                            {MODE_OPTIONS.map(m => (
                                <option key={m} value={m}>
                                    {m || '— none —'}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label className="flex flex-col gap-1 text-xs text-fg-subtle">
                        Advanced overrides (JSON, optional)
                        <input
                            type="text"
                            value={b.extra}
                            disabled={disabled}
                            onChange={e => update(i, { extra: e.target.value })}
                            placeholder='{"stale_duplicates_enabled": true}'
                            className="px-2 py-1 rounded bg-surface border border-border text-sm font-mono text-fg-muted"
                        />
                    </label>
                </div>
            ))}

            <div>
                <Button variant="secondary" onClick={add} disabled={disabled}>
                    + Add schedule block
                </Button>
            </div>
        </div>
    );
};
