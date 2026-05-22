// `navigator.clipboard.writeText` only works in a secure context (HTTPS or
// localhost). CHUB is commonly accessed over plain HTTP on a LAN IP, where
// the modern API is unavailable. Fall back to the legacy textarea +
// execCommand('copy') pattern, which still works in every browser CHUB
// targets and doesn't need user-gesture permissions beyond the click that
// triggered the copy.

/**
 * Copy text to the clipboard. Resolves on success, throws on failure.
 * @param {string} text
 * @returns {Promise<void>}
 */
export async function copyText(text) {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch {
            // Permission denied or transient failure — fall through to the
            // textarea fallback so the user still gets their copy.
        }
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    // Keep it off-screen and non-interactive, but still selectable.
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '0';
    textarea.style.left = '0';
    textarea.style.width = '1px';
    textarea.style.height = '1px';
    textarea.style.padding = '0';
    textarea.style.border = 'none';
    textarea.style.outline = 'none';
    textarea.style.boxShadow = 'none';
    textarea.style.background = 'transparent';
    textarea.style.opacity = '0';

    document.body.appendChild(textarea);
    try {
        textarea.select();
        textarea.setSelectionRange(0, text.length);
        const ok = document.execCommand('copy');
        if (!ok) throw new Error('execCommand returned false');
    } finally {
        document.body.removeChild(textarea);
    }
}
