/**
 * Shared datetime formatting helpers.
 *
 * Format is fixed to dd/mm/yyyy HH:MM:SS (24h) regardless of browser locale, so
 * timestamps render the same way the backend writes them in log files.
 */

const pad2 = n => String(n).padStart(2, '0');

const toDate = value => {
    if (value == null) return null;
    if (value instanceof Date) return value;
    if (typeof value === 'number') return new Date(value);
    if (typeof value === 'string') {
        // ISO without timezone: treat as UTC so server clocks line up with browser
        const looksNaiveIso = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(value);
        const d = looksNaiveIso ? new Date(value.replace(' ', 'T') + 'Z') : new Date(value);
        return Number.isNaN(d.getTime()) ? null : d;
    }
    return null;
};

/** dd/mm/yyyy HH:MM:SS */
export const formatDateTime = value => {
    const d = toDate(value);
    if (!d) return '';
    return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
};

/** dd/mm/yyyy */
export const formatDate = value => {
    const d = toDate(value);
    if (!d) return '';
    return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()}`;
};

/** HH:MM:SS */
export const formatTime = value => {
    const d = toDate(value);
    if (!d) return '';
    return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
};
