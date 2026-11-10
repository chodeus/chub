import { describe, expect, it, vi } from 'vitest';

import { showDeleteOutcome } from './deleteOutcome.js';

const toast = () => ({ success: vi.fn(), error: vi.fn() });

describe('showDeleteOutcome', () => {
    it('reports success when nothing failed', () => {
        const t = toast();
        showDeleteOutcome(t, { removed: [1, 2], failed: [] }, 'Deleted 2 copies');
        expect(t.success).toHaveBeenCalledWith('Deleted 2 copies');
        expect(t.error).not.toHaveBeenCalled();
    });

    it('reports the failures and their reasons, never as a success', () => {
        const t = toast();
        const failed = [
            { id: 2, reason: 'could not connect to Radarr 4K' },
            { id: 3, reason: 'could not connect to Radarr 4K' },
        ];
        showDeleteOutcome(t, { removed: [1], failed }, 'Deleted 3 copies');
        expect(t.success).not.toHaveBeenCalled();
        expect(t.error).toHaveBeenCalledWith(
            'Deleted 1, 2 not deleted: could not connect to Radarr 4K'
        );
    });

    it('leaves no dangling colon when no reason came back', () => {
        const t = toast();
        showDeleteOutcome(t, { removed: [1], failed: [{ id: 2 }] }, 'Deleted 2 copies');
        expect(t.error).toHaveBeenCalledWith('Deleted 1, 1 not deleted');
    });
});
