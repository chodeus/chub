// The registry resolves availability once at module load; in this test env the
// /api/version fetch fails, so every extension must read as unavailable.
import { describe, expect, it } from 'vitest';

import { extensionCapability, extensionRoutes, withExtensionNavChildren } from './index.js';

describe('extension gating (no backend => fail lean)', () => {
    it('reports no capabilities when nothing is enabled', () => {
        expect(extensionCapability('unmatchedRowAction')).toBeNull();
    });

    it('keeps every extension route mounted, swapped to the unavailable notice', () => {
        const routes = extensionRoutes();
        // Both bundled extensions contribute at least one route each.
        expect(routes.length).toBeGreaterThanOrEqual(2);
        for (const route of routes) {
            expect(route.Component.displayName ?? '').toMatch(/^ExtensionUnavailable\(/);
        }
    });

    it('splices no nav children while unavailable', () => {
        const sections = [{ items: [{ id: 'posters', children: [{ id: 'core-item' }] }] }];
        const out = withExtensionNavChildren(sections);
        expect(out[0].items[0].children).toHaveLength(1);
    });
});
