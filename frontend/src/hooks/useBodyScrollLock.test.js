import { renderHook } from '@testing-library/react';
import { useBodyScrollLock } from './useBodyScrollLock.js';

describe('useBodyScrollLock', () => {
    afterEach(() => {
        document.body.style.overflow = '';
    });

    it('holds the lock until the last holder releases it', () => {
        const first = renderHook(() => useBodyScrollLock(true));
        const second = renderHook(() => useBodyScrollLock(true));
        expect(document.body.style.overflow).toBe('hidden');

        first.unmount();
        // A second overlay is still open, so scrolling must stay locked.
        expect(document.body.style.overflow).toBe('hidden');

        second.unmount();
        expect(document.body.style.overflow).toBe('');
    });

    it('restores the overflow the page already had', () => {
        document.body.style.overflow = 'auto';

        const { unmount } = renderHook(() => useBodyScrollLock(true));
        expect(document.body.style.overflow).toBe('hidden');

        unmount();
        expect(document.body.style.overflow).toBe('auto');
    });

    it('leaves the body alone when not locked', () => {
        renderHook(() => useBodyScrollLock(false));

        expect(document.body.style.overflow).toBe('');
    });
});
