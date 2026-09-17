import { useMemo } from 'react';

/** Case-insensitive block filter: each matching LINE becomes its own block,
 *  keeping its parent block's levelClass. */
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
