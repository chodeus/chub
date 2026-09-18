/** Datetime helpers fixed to dd/mm/yyyy HH:MM:SS (24h) regardless of locale, matching how the backend writes log files. */

const pad2 = n => String(n).padStart(2, '0');

const toDate = value => {
    if (value == null) return null;
    let d = null;
    if (value instanceof Date) d = value;
    else if (typeof value === 'number') d = new Date(value);
    else if (typeof value === 'string') {
        // ISO without timezone: treat as UTC so server clocks line up with browser
        const looksNaiveIso = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(value);
        d = looksNaiveIso ? new Date(value.replace(' ', 'T') + 'Z') : new Date(value);
        // An out-of-range day rolls over ('2026-02-30' becomes 2026-03-02), so the calendar
        // date is checked alone: it names the same day whatever time or offset follows it.
        const datePart = /^(\d{4}-\d{2}-\d{2})/.exec(value);
        if (datePart) {
            const probe = new Date(`${datePart[1]}T00:00:00Z`);
            const rolled =
                Number.isNaN(probe.getTime()) || probe.toISOString().slice(0, 10) !== datePart[1];
            if (rolled) d = null;
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
