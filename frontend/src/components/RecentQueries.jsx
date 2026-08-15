import React, { useCallback, useState } from 'react';
import PropTypes from 'prop-types';

const MAX_ENTRIES = 6;

const readQueries = key => {
    try {
        const raw = localStorage.getItem(key);
        if (!raw) return [];
        const arr = JSON.parse(raw);
        return Array.isArray(arr) ? arr.slice(0, MAX_ENTRIES) : [];
    } catch {
        return [];
    }
};

const writeQueries = (key, entries) => {
    try {
        localStorage.setItem(key, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
    } catch {
        /* localStorage unavailable */
    }
};

/**
 * Lightweight "recent searches" strip for search pages. Stores entries in
 * localStorage under `storageKey`; clicking a chip replays the query via
 * `onSelect(query)`. Parent is responsible for calling `record(query)` after
 * a search actually runs.
 */
export function useRecentQueries(storageKey) {
    const [entries, setEntries] = useState(() => readQueries(storageKey));

    const record = useCallback(
        query => {
            const q = (query || '').trim();
            if (!q) return;
            setEntries(prev => {
                const next = [q, ...prev.filter(e => e !== q)].slice(0, MAX_ENTRIES);
                writeQueries(storageKey, next);
                return next;
            });
        },
        [storageKey]
    );

    const clear = useCallback(() => {
        writeQueries(storageKey, []);
        setEntries([]);
    }, [storageKey]);

    return { entries, record, clear };
}

export default function RecentQueries({ entries, onSelect, onClear, label = 'Recent' }) {
    const handleClearClick = useCallback(() => {
        if (!onClear) return;
        // Tiny confirm guard so "Clear" can't be tapped by accident when the
        // chip row gets crowded.
        if (typeof window !== 'undefined' && !window.confirm('Clear recent searches?')) return;
        onClear();
    }, [onClear]);

    if (!entries || entries.length === 0) return null;
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <span className="text-xs uppercase tracking-wider text-fg-subtle">{label}</span>
                {onClear && (
                    <button
                        type="button"
                        onClick={handleClearClick}
                        className="touch-expand inline-flex items-center text-xs text-fg-subtle hover:text-fg underline-offset-2 hover:underline bg-transparent border-0 p-0 cursor-pointer"
                    >
                        Clear
                    </button>
                )}
            </div>
            {/* min-w-11 keeps touch-expand's 44px box inside the chip, so a
                one-character query can't reach into its neighbour. */}
            <div className="flex flex-wrap items-center gap-2">
                {entries.map(q => (
                    <button
                        key={q}
                        type="button"
                        onClick={() => onSelect(q)}
                        className="touch-expand inline-flex items-center justify-center min-h-9 min-w-11 text-xs px-2.5 rounded-full bg-surface-alt text-fg-muted hover:bg-surface hover:text-fg border border-border-light"
                    >
                        {q}
                    </button>
                ))}
            </div>
        </div>
    );
}

RecentQueries.propTypes = {
    entries: PropTypes.arrayOf(PropTypes.string),
    onSelect: PropTypes.func.isRequired,
    onClear: PropTypes.func,
    label: PropTypes.string,
};
