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
    if (!entries || entries.length === 0) return null;
    return (
        <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs uppercase tracking-wider text-tertiary">{label}</span>
            {entries.map(q => (
                <button
                    key={q}
                    type="button"
                    onClick={() => onSelect(q)}
                    className="text-xs px-2.5 py-1 rounded-full bg-surface-alt text-secondary hover:bg-surface hover:text-primary border border-border-light"
                >
                    {q}
                </button>
            ))}
            {onClear && (
                <button
                    type="button"
                    onClick={onClear}
                    className="text-xs text-tertiary hover:text-primary underline-offset-2 hover:underline bg-transparent border-0 p-0 cursor-pointer"
                >
                    Clear
                </button>
            )}
        </div>
    );
}

RecentQueries.propTypes = {
    entries: PropTypes.arrayOf(PropTypes.string),
    onSelect: PropTypes.func.isRequired,
    onClear: PropTypes.func,
    label: PropTypes.string,
};
