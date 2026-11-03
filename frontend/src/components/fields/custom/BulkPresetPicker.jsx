/**
 * BulkPresetPicker - bulk-add GDrive preset drives (Sync GDrive)
 *
 * Renders above the gdrive_list accordion. Lets the user pick a global base
 * directory and tick multiple presets at once; each selected preset becomes a
 * gdrive_list entry { name, id, location } with location laid out as
 * {base}/{style}/{curator} (e.g. /posters/CL2K/Chodeus). The base starts as the
 * one the saved drives already use.
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

const isAbsolute = p => (p || '').trim().startsWith('/');

// Normalised path with no trailing slash: resolves "." / "..", collapses "//"; "/" becomes ''.
const trimPath = p => {
    const segments = [];
    (p || '')
        .trim()
        .split('/')
        .forEach(seg => {
            if (seg === '..') segments.pop();
            else if (seg && seg !== '.') segments.push(seg);
        });
    const joined = segments.join('/');
    return isAbsolute(p) && joined ? `/${joined}` : joined;
};

const parentOf = p => p.slice(0, p.lastIndexOf('/'));

// A bare "/" base must keep its slash or the location comes out relative.
const joinPath = (base, ...parts) => {
    const head = trimPath(base);
    const rest = parts.filter(Boolean).join('/');
    if (head) return rest ? `${head}/${rest}` : head;
    return isAbsolute(base) ? `/${rest}` : rest;
};

const usesStyleFolder = template => (template || '{base}/{style}/{name}') !== '{base}/{name}';

const buildLocation = (template, base, style, curator) =>
    usesStyleFolder(template) ? joinPath(base, style, curator) : joinPath(base, curator);

// Reverse of buildLocation over saved drives: the base most of them sit under,
// or '' when none qualify. Flat DAPS layouts (/posters/<curator>) count too.
const deriveBaseDir = (entries, styles, template) => {
    if (!styles.size) return '';
    const counts = new Map();
    (entries || []).forEach(entry => {
        const location = trimPath(entry?.location);
        if (!isAbsolute(location)) return;
        let base = parentOf(location);
        const folder = base.slice(base.lastIndexOf('/') + 1).toLowerCase();
        if (usesStyleFolder(template) && styles.has(folder)) base = parentOf(base);
        if (base) counts.set(base, (counts.get(base) ?? 0) + 1);
    });
    let best = '';
    counts.forEach((count, base) => {
        if (count > (counts.get(best) ?? 0)) best = base;
    });
    return best;
};

// Style folders already on disk under base, keyed lowercase, so new drives join an existing "cl2k".
const styleFoldersUnder = (entries, base, styles) => {
    const root = trimPath(base);
    const folders = new Map();
    (entries || []).forEach(entry => {
        const parent = parentOf(trimPath(entry?.location));
        const folder = parent.slice(parent.lastIndexOf('/') + 1);
        const key = folder.toLowerCase();
        if (parentOf(parent) === root && styles.has(key)) folders.set(key, folder);
    });
    return folders;
};

const isSameOrInside = (path, dir) => {
    const p = trimPath(path);
    const d = trimPath(dir);
    if (d) return p === d || p.startsWith(`${d}/`);
    // A "/" destination holds every absolute path.
    return isAbsolute(dir) && isAbsolute(path);
};

export const BulkPresetPicker = React.memo(
    ({ field, value = [], onChange, disabled = false, rootConfig }) => {
        const cfg = field.bulkPreset || {};
        const presetUrl = cfg.presetUrl || '/api/gdrive-presets';
        const template = cfg.locationTemplate || '{base}/{style}/{name}';

        const [presets, setPresets] = useState([]);
        const [loading, setLoading] = useState(false);
        // null until the user types; '' after they clear the box must stay cleared.
        const [typedBase, setTypedBase] = useState(null);

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

        const savedById = useMemo(
            () => new Map((value || []).filter(e => e?.id).map(e => [e.id, e.location ?? ''])),
            [value]
        );

        const styles = useMemo(
            () => new Set(presets.map(p => p?.style?.toLowerCase()).filter(Boolean)),
            [presets]
        );
        const derivedBase = useMemo(
            () => deriveBaseDir(value, styles, template),
            [value, styles, template]
        );
        const baseDir = typedBase ?? derivedBase;

        const styleFolders = useMemo(
            () => styleFoldersUnder(value, baseDir, styles),
            [value, baseDir, styles]
        );
        const locationFor = useCallback(
            p =>
                buildLocation(
                    template,
                    baseDir,
                    styleFolders.get(p.style?.toLowerCase()) ?? p.style,
                    curatorOf(p)
                ),
            [template, baseDir, styleFolders]
        );

        // Only the Kometa apply method writes to destination_dir; Plex uploads directly.
        const renamerr = rootConfig?.poster_renamerr;
        const destinationDir =
            (renamerr?.apply_method ?? 'kometa') === 'kometa' ? renamerr?.destination_dir : '';
        const insideDestination = isSameOrInside(baseDir, destinationDir);

        // Group presets by style; added drives show their saved location, the rest a live preview.
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
                    items: byStyle[style].map(p => {
                        const added = savedById.has(p.id);
                        return {
                            value: p.id,
                            label: p.name,
                            sublabel: added ? savedById.get(p.id) : locationFor(p),
                            disabled: added,
                        };
                    }),
                }));
        }, [presets, locationFor, savedById]);

        const handleAdd = useCallback(
            selectedIds => {
                const byId = new Map(presets.map(p => [p.id, p]));
                const additions = [];
                selectedIds.forEach(id => {
                    if (savedById.has(id)) return;
                    const p = byId.get(id);
                    if (!p) return;
                    additions.push({
                        name: p.name,
                        id: p.id,
                        location: locationFor(p),
                    });
                });
                if (additions.length) onChange([...(value || []), ...additions]);
            },
            [presets, savedById, locationFor, value, onChange]
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
                    placeholder="e.g. /posters"
                    disabled={disabled}
                    onChange={e => setTypedBase(e.target.value)}
                    aria-describedby={
                        insideDestination
                            ? 'bulk_base_dir-desc bulk_base_dir-warn'
                            : 'bulk_base_dir-desc'
                    }
                />
                {insideDestination && (
                    <p
                        id="bulk_base_dir-warn"
                        role="status"
                        className="flex items-center gap-1.5 text-xs text-warning"
                    >
                        <span className="material-symbols-outlined text-sm leading-none">
                            warning
                        </span>
                        <span>
                            This is Poster Renamerr&apos;s destination directory (
                            {trimPath(destinationDir)}) or a folder inside it. Drives synced here
                            mix with the renamed posters Kometa reads — use a folder outside it.
                        </span>
                    </p>
                )}
                <FieldDescription
                    id="bulk_base_dir-desc"
                    description="Drives are organised into {style}/{curator} subfolders here, e.g. /posters/CL2K/Chodeus. Filled in from the drives you've already added. CL2K and MM2K are poster styles; Artwork drives hold logos, backgrounds and square art — add those to Asset Renamerr's source directories to use them. Square art works on both apply paths (Kometa 2.4.5+)."
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
    }
);

BulkPresetPicker.displayName = 'BulkPresetPicker';

export default BulkPresetPicker;
