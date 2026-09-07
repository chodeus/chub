/** Formats an external ID for display — returns null if empty/falsy */
export const formatId = val => (val ? String(val) : null);

/** Build a Discord-ready poster-request block for a single item.
 * Returns {text, hasTmdb} or null when no usable id is available.
 *
 * For series with exactly one missing season and no missing main poster,
 * the TMDb link points directly at that season's page so the recipient
 * lands on the right poster spread instead of the show's main page.
 *
 * The backend resolves most missing tmdb_id values via TMDB's /find API
 * (configurable under Settings → TMDB), so this fallback chain rarely
 * reaches TVDb in practice. */
export const buildPosterRequestText = (item, type) => {
    const title = item.title || 'Unknown';
    const year = item.year ? ` (${item.year})` : '';
    const lines = [`${title}${year}`];

    const missingSeasons = type === 'series' ? item.missing_seasons || [] : [];
    const onlyOneMissingSeason =
        type === 'series' && missingSeasons.length === 1 && !item.missing_main_poster;

    let hasTmdb = false;
    if (type === 'movie' && item.tmdb_id) {
        lines.push(`https://www.themoviedb.org/movie/${item.tmdb_id}`);
        hasTmdb = true;
    } else if (type === 'series' && item.tmdb_id) {
        if (onlyOneMissingSeason) {
            lines.push(`https://www.themoviedb.org/tv/${item.tmdb_id}/season/${missingSeasons[0]}`);
        } else {
            lines.push(`https://www.themoviedb.org/tv/${item.tmdb_id}`);
        }
        hasTmdb = true;
    } else if (type === 'series' && item.tvdb_id) {
        lines.push(`https://thetvdb.com/?tab=series&id=${item.tvdb_id}`);
    } else {
        return null;
    }

    if (type === 'series') {
        if (item.missing_main_poster) lines.push('Missing main poster');
        if (missingSeasons.length > 0) {
            lines.push(`Missing seasons: ${missingSeasons.join(', ')}`);
        }
    }
    return { text: lines.join('\n'), hasTmdb };
};
