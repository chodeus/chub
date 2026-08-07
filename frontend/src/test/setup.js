import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach } from 'vitest';

// jsdom doesn't expose localStorage here, and UIStateProvider + the Cleanarr
// tree read it on mount.
if (!globalThis.localStorage) {
    const store = new Map();
    globalThis.localStorage = {
        getItem: k => (store.has(k) ? store.get(k) : null),
        setItem: (k, v) => store.set(k, String(v)),
        removeItem: k => store.delete(k),
        clear: () => store.clear(),
        key: i => [...store.keys()][i] ?? null,
        get length() {
            return store.size;
        },
    };
}

// Modal portals into #modal-root, which lives in index.html — without it every
// modal renders nothing and assertions fail as "no dialog" rather than a mount error.
beforeEach(() => {
    const root = document.createElement('div');
    root.id = 'modal-root';
    document.body.appendChild(root);
});

afterEach(() => {
    cleanup();
    document.getElementById('modal-root')?.remove();
});

// jsdom implements neither, and both are used during render — matchMedia by the
// mobile/pointer hooks, IntersectionObserver by lazy-loading grids.
// Plain functions, NOT vi.fn(): `restoreMocks` strips a mock's implementation
// between tests, which would make matchMedia() return undefined on test 2+.
if (!window.matchMedia) {
    window.matchMedia = query => ({
        matches: false,
        media: query,
        onchange: null,
        addListener() {},
        removeListener() {},
        addEventListener() {},
        removeEventListener() {},
        dispatchEvent() {
            return false;
        },
    });
}

if (!window.IntersectionObserver) {
    window.IntersectionObserver = class {
        observe() {}
        unobserve() {}
        disconnect() {}
    };
}
