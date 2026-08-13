// Single owner for blob downloads. WebKit cancels an in-flight download when
// the object URL is revoked synchronously after the click — hence the delay.

const REVOKE_DELAY_MS = 1000;

/**
 * Trigger a browser download of a blob under the given filename.
 * @param {Blob} blob - Data to download
 * @param {string} filename - Suggested filename
 * @returns {void}
 */
export function downloadBlob(blob, filename) {
    const objectUrl = URL.createObjectURL(blob);
    // createElement is the only statement that may precede the try — anything
    // throwing before it would leak the object URL.
    const link = document.createElement('a');
    try {
        link.href = objectUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
    } finally {
        link.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), REVOKE_DELAY_MS);
    }
}
