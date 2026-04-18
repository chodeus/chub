import { useState, useCallback } from 'react';

const STORAGE_KEY = 'chub_recent_searches';
const MAX_RECENT = 8;

/**
 * Hook for managing recent search history in localStorage
 * @returns {{ recentSearches: string[], addSearch: (term: string) => void, clearSearches: () => void }}
 */
export function useRecentSearches() {
    const [recentSearches, setRecentSearches] = useState(() => {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        } catch {
            return [];
        }
    });

    const addSearch = useCallback(term => {
        if (!term || !term.trim()) return;
        const trimmed = term.trim();
        setRecentSearches(prev => {
            const filtered = prev.filter(s => s !== trimmed);
            const next = [trimmed, ...filtered].slice(0, MAX_RECENT);
            try {
                localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
            } catch {
                // Ignore storage errors
            }
            return next;
        });
    }, []);

    const clearSearches = useCallback(() => {
        setRecentSearches([]);
        try {
            localStorage.removeItem(STORAGE_KEY);
        } catch {
            // Ignore storage errors
        }
    }, []);

    return { recentSearches, addSearch, clearSearches };
}
