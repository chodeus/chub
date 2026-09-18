import { useEffect } from 'react';

const DEFAULT_MESSAGE = 'You have unsaved changes. Leave this page and discard them?';

const isPlainLeftClick = event =>
    event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;

const sameDocumentUrl = href => {
    try {
        const nextUrl = new URL(href, window.location.href);
        const currentUrl = new URL(window.location.href);

        return (
            nextUrl.origin === currentUrl.origin &&
            nextUrl.pathname === currentUrl.pathname &&
            nextUrl.search === currentUrl.search &&
            nextUrl.hash === currentUrl.hash
        );
    } catch {
        return false;
    }
};

/** Warns before discarding unsaved changes, on unload and in-app anchor navigation.
 *  `useBlocker` is unavailable: the app mounts BrowserRouter, not a data router. */
export function useUnsavedChangesWarning(isDirty, message = DEFAULT_MESSAGE) {
    useEffect(() => {
        if (!isDirty) return undefined;

        const handleBeforeUnload = event => {
            event.preventDefault();
            event.returnValue = '';
        };

        window.addEventListener('beforeunload', handleBeforeUnload);
        return () => window.removeEventListener('beforeunload', handleBeforeUnload);
    }, [isDirty]);

    useEffect(() => {
        if (!isDirty) return undefined;

        const handleDocumentClick = event => {
            if (event.defaultPrevented || !isPlainLeftClick(event)) return;

            const anchor = event.target.closest?.('a[href]');
            if (!anchor || anchor.target || anchor.hasAttribute('download')) return;
            if (sameDocumentUrl(anchor.href)) return;

            const nextUrl = new URL(anchor.href, window.location.href);
            if (nextUrl.origin !== window.location.origin) return;

            if (!window.confirm(message)) {
                event.preventDefault();
                event.stopPropagation();
            }
        };

        document.addEventListener('click', handleDocumentClick, true);
        return () => document.removeEventListener('click', handleDocumentClick, true);
    }, [isDirty, message]);
}
