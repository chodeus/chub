import { useMemo } from 'react';

/**
 * useLogSearch - Filter blocks by search term (case-insensitive).
 *
 * When a search term is set, the result switches to per-line matching: each
 * matching line is returned as its own synthetic block (preserving its
 * parent block's levelClass for styling). The previous behavior kept whole
 * blocks where any line matched, which surfaced unrelated lines that
 * happened to share a parent block (e.g. searching "Movies" matched the
 * INFO block holding the "| Movies |" table header but missed every
 * data row underneath because the row blocks didn't contain "Movies").
 *
 * @param {Array<{lines: string[], levelClass: string}>} blocks - Parsed log blocks
 * @param {string} searchTerm - Search term (case-insensitive)
 * @returns {Array<{lines: string[], levelClass: string}>} Filtered blocks
 */
export function useLogSearch(blocks, searchTerm) {
    return useMemo(() => {
        if (!searchTerm || !searchTerm.trim()) {
            return blocks;
        }

        const lowerSearch = searchTerm.toLowerCase();
        const matchingLines = [];
        for (const block of blocks) {
            for (const line of block.lines) {
                if (line.toLowerCase().includes(lowerSearch)) {
                    matchingLines.push({ lines: [line], levelClass: block.levelClass });
                }
            }
        }
        return matchingLines;
    }, [blocks, searchTerm]);
}
