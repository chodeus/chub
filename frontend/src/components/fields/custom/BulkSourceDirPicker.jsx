/**
 * BulkSourceDirPicker - bulk-add configured GDrive locations as source dirs
 *
 * Renders above the Poster Renamerr source_dirs drag-drop list. Pulls the
 * drives already configured in Sync GDrive (via the GDrive-sources search
 * endpoint) and lets the user tick several at once; each selected drive's
 * local location string is appended to source_dirs.
 *
 * Sourcing from configured drives (not the raw preset catalogue) guarantees the
 * paths line up with what Sync GDrive actually writes — no path mismatch. The
 * user then drags to set priority; single-add stays on the list below. Appends
 * only, deduping against paths already present.
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { BulkSelectList } from './BulkSelectList';
import { postersAPI } from '../../../utils/api/posters.js';

export const BulkSourceDirPicker = React.memo(
    ({ directories = [], onChange, disabled = false }) => {
        const [sources, setSources] = useState([]);
        const [loading, setLoading] = useState(false);

        useEffect(() => {
            let mounted = true;
            setLoading(true);
            postersAPI
                .searchGoogleDrive({})
                .then(resp => {
                    const list = resp?.data?.sources;
                    if (mounted && Array.isArray(list)) setSources(list);
                })
                .catch(() => mounted && setSources([]))
                .finally(() => mounted && setLoading(false));
            return () => {
                mounted = false;
            };
        }, []);

        // Existing source paths (ignoring the empty-init placeholder entry).
        const existing = useMemo(
            () => new Set((directories || []).map(d => d?.trim()).filter(Boolean)),
            [directories]
        );

        const groups = useMemo(() => {
            const items = sources
                .filter(s => s?.location)
                .map(s => ({
                    value: s.location,
                    label: s.name || s.location,
                    sublabel: s.location,
                    disabled: existing.has(s.location.trim()),
                }));
            return [{ key: 'drives', label: '', items }];
        }, [sources, existing]);

        const handleAdd = useCallback(
            selectedPaths => {
                const additions = selectedPaths.filter(p => p && !existing.has(p.trim()));
                if (!additions.length) return;
                const base = (directories || []).filter(d => d && d.trim());
                onChange([...base, ...additions]);
            },
            [existing, directories, onChange]
        );

        return (
            <BulkSelectList
                title="Bulk-add configured Google Drives"
                loading={loading}
                groups={groups}
                addButtonText={count => `Add ${count} selected drive${count === 1 ? '' : 's'}`}
                onAdd={handleAdd}
                emptyMessage="No Google Drives configured yet. Add them in Sync GDrive first."
                disabled={disabled}
            />
        );
    }
);

BulkSourceDirPicker.displayName = 'BulkSourceDirPicker';

export default BulkSourceDirPicker;
