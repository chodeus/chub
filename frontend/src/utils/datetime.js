/**
 * Shared datetime formatting helpers.
 *
 * Format is fixed to dd/mm/yyyy HH:MM:SS (24h) regardless of browser locale, so
 * timestamps render the same way the backend writes them in log files.
 */

const pad2 = n => String(n).padStart(2, '0');

const toDate = value => {
    if (value == null) return null;
    let d = null;
    if (value instanceof Date) d = value;
    else if (typeof value === 'number') d = new Date(value);
    else if (typeof value === 'string') {
        // ISO without timezone: treat as UTC so server clocks line up with browser
        const looksNaiveIso = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(value);
        const isoDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
        d = looksNaiveIso ? new Date(value.replace(' ', 'T') + 'Z') : new Date(value);
        // An out-of-range day rolls over ('2026-02-30' parses as 2026-03-02), so getTime()
        // accepts a date nobody wrote. Only these two forms are UTC-anchored enough to compare.
        if (
            (looksNaiveIso || isoDateOnly) &&
            !Number.isNaN(d.getTime()) &&
            d.toISOString().slice(0, 10) !== value.slice(0, 10)
        ) {
            d = null;
        }
    }
    // One validity check for every branch: an invalid Date passed straight in and
    // `new Date(NaN)` both format as NaN/NaN/NaN otherwise.
    return d && !Number.isNaN(d.getTime()) ? d : null;
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
