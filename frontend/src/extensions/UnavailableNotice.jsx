import React from 'react';

/** Page shown when an extension route is opened on an image that doesn't carry it. */
export function makeUnavailableNotice(pageName) {
    const Notice = () => (
        <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
            <span
                className="material-symbols-rounded text-fg-subtle"
                style={{ fontSize: '44px' }}
                aria-hidden="true"
            >
                extension_off
            </span>
            <h1 className="text-lg font-semibold text-fg">
                {pageName} ships in the <code>:full</code> image
            </h1>
            <p className="max-w-md text-sm text-fg-muted">
                This install runs the minimal <code>ghcr.io/chodeus/chub:latest</code> image. Switch
                the container to the <code>:full</code> tag to enable it — your config and data
                carry over unchanged.
            </p>
        </div>
    );
    Notice.displayName = `ExtensionUnavailable(${pageName})`;
    return Notice;
}
