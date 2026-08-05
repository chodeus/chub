/**
 * BulkPresetPicker - bulk-add GDrive preset drives (Sync GDrive)
 *
 * Renders above the gdrive_list accordion. Lets the user pick a global base
 * directory and tick multiple presets at once; each selected preset becomes a
 * gdrive_list entry { name, id, location } with location laid out as
 * {base}/{style}/{curator} (e.g. /kometa/posters/CL2K/Chodeus).
 *
 * Single-add and per-entry editing remain on the accordion below — this only
 * appends, deduping against existing entries by GDrive id.
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { BulkSelectList } from './BulkSelectList';
import { FieldLabel, FieldDescription, InputBase } from '../primitives';
import { fetchGdrivePresets } from '../../../utils/gdrivePresets.js';

// Strip the "STYLE " prefix that the preset catalogue display-name carries,
// recovering the bare curator name used for the per-style subfolder.
const curatorOf = preset => {
    const prefix = `${preset.style} `;
    return preset.name?.startsWith(prefix) ? preset.name.slice(prefix.length) : preset.name;
};

const joinPath = (base, ...parts) => {
    const trimmed = (base || '').replace(/\/+$/, '');
    return [trimmed, ...parts].filter(Boolean).join('/');
};

const buildLocation = (template, base, style, curator) =>
    (template || '{base}/{style}/{name}') === '{base}/{name}'
        ? joinPath(base, curator)
        : joinPath(base, style, curator);

export const BulkPresetPicker = React.memo(({ field, value = [], onChange, disabled = false }) => {
    const cfg = field.bulkPreset || {};
    const presetUrl = cfg.presetUrl || '/api/gdrive-presets';
    const template = cfg.locationTemplate || '{base}/{style}/{name}';

    const [presets, setPresets] = useState([]);
    const [loading, setLoading] = useState(false);
    const [baseDir, setBaseDir] = useState('');

    useEffect(() => {
        let mounted = true;
        setLoading(true);
        fetchGdrivePresets(presetUrl)
            .then(arr => mounted && setPresets(arr))
            .finally(() => mounted && setLoading(false));
        return () => {
            mounted = false;
        };
    }, [presetUrl]);

    const existingIds = useMemo(
        () => new Set((value || []).map(e => e?.id).filter(Boolean)),
        [value]
    );

    // Group presets by style, computing a live location preview as the sublabel.
    const groups = useMemo(() => {
        const byStyle = {};
        presets.forEach(p => {
            if (!p?.id) return;
            const style = p.style || 'Other';
            (byStyle[style] = byStyle[style] || []).push(p);
        });
        return Object.keys(byStyle)
            .sort()
            .map(style => ({
                key: style,
                label: style,
                items: byStyle[style].map(p => ({
                    value: p.id,
                    label: p.name,
                    sublabel: buildLocation(template, baseDir, p.style, curatorOf(p)),
                    disabled: existingIds.has(p.id),
                })),
            }));
    }, [presets, baseDir, template, existingIds]);

    const handleAdd = useCallback(
        selectedIds => {
            const byId = new Map(presets.map(p => [p.id, p]));
            const additions = [];
            selectedIds.forEach(id => {
                if (existingIds.has(id)) return;
                const p = byId.get(id);
                if (!p) return;
                additions.push({
                    name: p.name,
                    id: p.id,
                    location: buildLocation(template, baseDir, p.style, curatorOf(p)),
                });
            });
            if (additions.length) onChange([...(value || []), ...additions]);
        },
        [presets, existingIds, baseDir, template, value, onChange]
    );

    const canAdd = !!baseDir.trim();

    const headerSlot = (
        <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="bulk_base_dir" label="Global base directory" />
            <InputBase
                id="bulk_base_dir"
                name="bulk_base_dir"
                type="text"
                value={baseDir}
                placeholder="/kometa/posters"
                disabled={disabled}
                onChange={e => setBaseDir(e.target.value)}
                aria-describedby="bulk_base_dir-desc"
            />
            <FieldDescription
                id="bulk_base_dir-desc"
                description="Drives are organised into {style}/{curator} subfolders here, e.g. /kometa/posters/CL2K/Chodeus. CL2K and MM2K are poster styles; Artwork drives hold logos, backgrounds and square art — add those to Asset Renamerr's source directories to use them. Square art applies on the Plex path only; Kometa doesn't read it from asset folders."
            />
        </div>
    );

    return (
        <BulkSelectList
            title="Bulk-add from presets"
            loading={loading}
            groups={groups}
            headerSlot={headerSlot}
            canAdd={canAdd}
            addDisabledReason="Set a global base directory to enable bulk-add."
            addButtonText={count => `Add ${count} selected drive${count === 1 ? '' : 's'}`}
            onAdd={handleAdd}
            emptyMessage="No presets available."
            disabled={disabled}
        />
    );
});

BulkPresetPicker.displayName = 'BulkPresetPicker';

export default BulkPresetPicker;
