import React, { useState, useCallback, useMemo, useEffect } from 'react';
import PropTypes from 'prop-types';
import { useSearch, SEARCH_TYPES } from '../../contexts/SearchCoordinatorContext.jsx';
import { useToast } from '../../contexts/ToastContext.jsx';
import { useApiMutation } from '../../hooks/useApiData.js';
import { mediaAPI } from '../../utils/api/media.js';
import { Modal } from '../../components/modals/Modal';
import { Button, IconButton, Pagination, SegmentedControl } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';
import RecentQueries, { useRecentQueries } from '../../components/RecentQueries.jsx';
import { formatDate } from '../../utils/datetime.js';

const POSTER_W = 58;
const POSTER_H = 86;
// Diagonal-stripe placeholder mirroring the mock's missing-poster affordance.
const POSTER_STRIPES = 'repeating-linear-gradient(135deg,#221c45 0 6px,#1c1740 6px 12px)';

// genre/tags are stored as JSON-array TEXT (e.g. '["Action","Crime"]'). Parse
// to a clean array; tolerate a plain string or already-parsed array.
function parseJsonList(value) {
    if (Array.isArray(value)) return value.filter(Boolean);
    if (typeof value !== 'string' || !value.trim()) return [];
    try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed.filter(Boolean) : [value];
    } catch {
        return [value];
    }
}

// Colour the instance dot by service so a row reads at a glance.
function instanceDotColor(name) {
    const n = (name || '').toLowerCase();
    if (n.includes('radarr')) return '#6cbc66';
    if (n.includes('sonarr')) return '#53e8f0';
    if (n.includes('lidarr')) return '#9a7ba9';
    if (n.includes('plex')) return '#e28b2d';
    return '#6582ca';
}

function PosterThumb({ mediaId }) {
    const [errored, setErrored] = useState(false);
    const src = mediaAPI.getPosterUrl(mediaId);
    if (errored || !src) {
        return (
            <div
                className="flex-none flex items-center justify-center rounded-[7px] border border-border"
                style={{ width: POSTER_W, height: POSTER_H, background: POSTER_STRIPES }}
            >
                <span className="material-symbols-outlined text-fg-muted text-[18px]">image</span>
            </div>
        );
    }
    return (
        <img
            src={src}
            alt=""
            loading="lazy"
            onError={() => setErrored(true)}
            className="flex-none rounded-[7px] object-cover border border-border bg-surface-inset"
            style={{ width: POSTER_W, height: POSTER_H }}
        />
    );
}

PosterThumb.propTypes = {
    mediaId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
};

const FILTER_STORAGE_KEY = 'chub_media_search_filters';

function loadSavedFilters() {
    try {
        const saved = localStorage.getItem(FILTER_STORAGE_KEY);
        if (saved) return JSON.parse(saved);
    } catch {
        /* ignore */
    }
    return null;
}

function saveFilters(filters) {
    try {
        localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(filters));
    } catch {
        /* ignore */
    }
}

const TYPE_OPTIONS = [
    { value: 'all', label: 'All' },
    { value: 'movie', label: 'Movies' },
    { value: 'show', label: 'Shows' },
];

const MediaSearchPage = () => {
    const toast = useToast();

    const saved = useMemo(() => loadSavedFilters(), []);
    const [filters, setFilters] = useState({
        type: saved?.type || 'all',
        sort: saved?.sort || 'title',
        order: saved?.order || 'asc',
        limit: 50,
        offset: 0,
    });

    // Persist filter changes (excluding offset/limit)
    useEffect(() => {
        saveFilters({ type: filters.type, sort: filters.sort, order: filters.order });
    }, [filters.type, filters.sort, filters.order]);
    const [deleteTarget, setDeleteTarget] = useState(null);

    const { execute: deleteItem, isLoading: isDeleting } = useApiMutation(
        () => mediaAPI.deleteMediaItem(deleteTarget?.id),
        { successMessage: 'Media item deleted' }
    );

    const searchFunction = useCallback(
        term =>
            mediaAPI.searchMedia({
                query: term,
                type: filters.type !== 'all' ? filters.type : undefined,
                sort: filters.sort,
                order: filters.order,
                limit: filters.limit,
                offset: filters.offset,
            }),
        [filters]
    );

    const { term, results, isSearching, hasResults, totalCount, search } = useSearch(
        SEARCH_TYPES.MEDIA,
        searchFunction
    );

    // In-page search field, wired to the shared SearchCoordinator (debounced
    // there). Mirrors the committed `term` so external triggers (recent-query
    // clicks, the header search) keep the field in sync — synced by adjusting
    // state during render (no effect) per the React "previous value" pattern.
    const [query, setQuery] = useState(term || '');
    const [prevTerm, setPrevTerm] = useState(term);
    if (term !== prevTerm) {
        setPrevTerm(term);
        setQuery(term || '');
    }
    const handleQueryChange = useCallback(
        e => {
            const v = e.target.value;
            setQuery(v);
            search(v);
        },
        [search]
    );

    const recent = useRecentQueries('chub_media_search_recent');
    useEffect(() => {
        if (term && hasResults) recent.record(term);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [term, hasResults]);

    const items = useMemo(() => results?.data?.items || results?.items || [], [results]);
    const total = useMemo(
        () => results?.data?.total || results?.total || totalCount || 0,
        [results, totalCount]
    );

    const handleDelete = async () => {
        if (!deleteTarget) return;
        try {
            await deleteItem();
            toast.success(`Deleted "${deleteTarget.title}"`);
            setDeleteTarget(null);
            if (term) search(term, { immediate: true });
        } catch {
            toast.error('Failed to delete media item');
        }
    };

    return (
        <div className="flex flex-col gap-5">
            {/* Toolbar */}
            <div>
                <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                    Library
                </h1>
                <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                    Search and discover content across your media instances.
                </p>
            </div>

            {/* Search + filters */}
            <div className="flex flex-wrap items-center gap-3">
                <div className="flex-1 min-w-[240px] flex items-center gap-2.5 h-11 px-3.5 rounded-[10px] bg-surface border border-border focus-within:border-primary transition-colors">
                    <span className="material-symbols-outlined text-[18px] text-fg-subtle">
                        search
                    </span>
                    <input
                        value={query}
                        onChange={handleQueryChange}
                        placeholder="Search your library…"
                        className="flex-1 min-w-0 bg-transparent border-0 outline-none text-sm text-fg placeholder:text-fg-subtle"
                        aria-label="Search library"
                    />
                    {hasResults && (
                        <span className="font-mono text-[11px] text-fg-faint shrink-0">
                            {total} results
                        </span>
                    )}
                </div>
                <SegmentedControl
                    options={TYPE_OPTIONS}
                    value={filters.type}
                    onChange={v => setFilters(prev => ({ ...prev, type: v, offset: 0 }))}
                />
                <div className="flex items-center h-11 rounded-[10px] bg-surface border border-border">
                    <span className="material-symbols-outlined text-[16px] text-fg-subtle pl-3">
                        sort
                    </span>
                    <select
                        value={filters.sort}
                        onChange={e => setFilters(prev => ({ ...prev, sort: e.target.value }))}
                        className="h-full bg-transparent border-0 outline-none text-[13.5px] text-fg-muted pl-1.5 pr-3 cursor-pointer"
                        aria-label="Sort results"
                    >
                        <option value="title">Sort: Title</option>
                        <option value="year">Sort: Year</option>
                        <option value="rating">Sort: Rating</option>
                        <option value="runtime">Sort: Runtime</option>
                    </select>
                </div>
            </div>

            {isSearching && <Spinner size="large" text="Searching..." center />}

            {!isSearching && !term && (
                <div className="flex flex-col items-center gap-6 py-10 text-fg-subtle">
                    <div className="text-center">
                        <span className="material-symbols-outlined text-5xl mb-4 block opacity-40">
                            search
                        </span>
                        <p className="text-lg">Search your library by title</p>
                        <p className="text-sm mt-2">Across all your configured instances</p>
                    </div>
                    {recent.entries.length > 0 && (
                        <RecentQueries
                            entries={recent.entries}
                            onSelect={q => search(q, { immediate: true })}
                            onClear={recent.clear}
                            label="Recent searches"
                        />
                    )}
                </div>
            )}

            {!isSearching && term && !hasResults && (
                <div className="text-center py-16 text-fg-subtle">
                    <span className="material-symbols-outlined text-5xl mb-4 block opacity-40">
                        search_off
                    </span>
                    <p className="text-lg">No results found for &quot;{term}&quot;</p>
                </div>
            )}

            {hasResults && (
                <>
                    <p className="font-mono text-[11.5px] text-fg-subtle m-0">
                        {total} result{total !== 1 ? 's' : ''} for &quot;{term}&quot;
                    </p>
                    <div className="flex flex-col gap-3">
                        {items.map(item => {
                            const tmdbPath = item.asset_type === 'movie' ? 'movie' : 'tv';
                            const externalLinks = [
                                item.tmdb_id &&
                                    item.asset_type !== 'artist' && {
                                        label: 'TMDB',
                                        value: item.tmdb_id,
                                        href: `https://www.themoviedb.org/${tmdbPath}/${item.tmdb_id}`,
                                    },
                                item.tvdb_id && {
                                    label: 'TVDB',
                                    value: item.tvdb_id,
                                    href: `https://thetvdb.com/dereferrer/series/${item.tvdb_id}`,
                                },
                                item.imdb_id && {
                                    label: 'IMDb',
                                    value: item.imdb_id,
                                    href: `https://www.imdb.com/title/${item.imdb_id}`,
                                },
                                item.musicbrainz_id && {
                                    label: 'MusicBrainz',
                                    value: item.musicbrainz_id,
                                    href: `https://musicbrainz.org/artist/${item.musicbrainz_id}`,
                                },
                            ].filter(Boolean);
                            const genres = parseJsonList(item.genre);
                            const tags = parseJsonList(item.tags);
                            const runtime =
                                item.runtime != null && item.runtime > 0
                                    ? item.runtime >= 60
                                        ? `${Math.floor(item.runtime / 60)}h ${item.runtime % 60}m`
                                        : `${item.runtime}m`
                                    : null;
                            const meta = [
                                item.asset_type && {
                                    key: 'type',
                                    node: (
                                        <span className="capitalize text-fg-muted">
                                            {item.asset_type}
                                        </span>
                                    ),
                                },
                                item.instance_name && {
                                    key: 'inst',
                                    node: (
                                        <span className="flex items-center gap-1.5">
                                            <span
                                                className="w-1.5 h-1.5 rounded-full"
                                                style={{
                                                    background: instanceDotColor(
                                                        item.instance_name
                                                    ),
                                                }}
                                            />
                                            {item.instance_name}
                                        </span>
                                    ),
                                },
                                item.rating != null && {
                                    key: 'rating',
                                    node: <span className="text-warning">★ {item.rating}</span>,
                                },
                                runtime && { key: 'runtime', node: <span>{runtime}</span> },
                                item.language && {
                                    key: 'lang',
                                    node: <span className="uppercase">{item.language}</span>,
                                },
                            ].filter(Boolean);
                            return (
                                <div
                                    key={item.id}
                                    className="group flex gap-4 p-3.5 rounded-xl bg-surface border border-border hover:border-[#3b3d72] transition-colors"
                                >
                                    <PosterThumb mediaId={item.id} />
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-start justify-between gap-3">
                                            <div className="flex items-baseline gap-2.5 flex-wrap min-w-0">
                                                <span className="font-display text-[16px] font-semibold text-fg">
                                                    {item.title}
                                                </span>
                                                {item.year && (
                                                    <span className="font-mono text-xs text-fg-subtle">
                                                        {item.year}
                                                    </span>
                                                )}
                                                {item.season_number != null && (
                                                    <span className="font-mono text-[10px] px-[7px] py-0.5 rounded-[5px] bg-primary/15 text-source-cl2k">
                                                        {item.season_number === 0
                                                            ? 'Specials'
                                                            : `Season ${item.season_number}`}
                                                    </span>
                                                )}
                                            </div>
                                            <div className="flex items-center gap-1.5 shrink-0">
                                                <span
                                                    className={`font-mono text-[10px] font-semibold px-[9px] py-[3px] rounded-full ${
                                                        item.matched
                                                            ? 'bg-success/15 text-success'
                                                            : 'bg-warning/15 text-warning'
                                                    }`}
                                                >
                                                    {item.matched ? 'MATCHED' : 'UNMATCHED'}
                                                </span>
                                                <IconButton
                                                    icon="delete"
                                                    aria-label="Delete"
                                                    variant="ghost"
                                                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                                                    onClick={() => setDeleteTarget(item)}
                                                />
                                            </div>
                                        </div>

                                        {meta.length > 0 && (
                                            <div className="flex items-center gap-2.5 flex-wrap mt-1.5 font-mono text-[11.5px] text-fg-data">
                                                {meta.map((m, i) => (
                                                    <React.Fragment key={m.key}>
                                                        {i > 0 && (
                                                            <span className="text-fg-dim">·</span>
                                                        )}
                                                        {m.node}
                                                    </React.Fragment>
                                                ))}
                                            </div>
                                        )}

                                        {genres.length > 0 && (
                                            <div className="text-[12.5px] text-fg-subtle mt-1.5">
                                                {genres.join(' · ')}
                                            </div>
                                        )}

                                        {externalLinks.length > 0 && (
                                            <div className="flex items-center gap-1.5 flex-wrap mt-2">
                                                {externalLinks.map(link => (
                                                    <a
                                                        key={link.label}
                                                        href={link.href}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="font-mono text-[10.5px] px-2 py-0.5 rounded-[5px] bg-surface-inset text-accent hover:text-source-cl2k transition-colors no-underline"
                                                    >
                                                        {link.label} {link.value}
                                                    </a>
                                                ))}
                                            </div>
                                        )}

                                        {tags.length > 0 && (
                                            <div className="flex items-center gap-1.5 flex-wrap mt-2">
                                                {tags.map(tag => (
                                                    <span
                                                        key={tag}
                                                        className="font-mono text-[10.5px] px-2 py-0.5 rounded-[5px] bg-surface-inset text-fg-subtle"
                                                    >
                                                        {tag}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        {item.media_file && (
                                            <div className="font-mono text-[11px] text-fg-dim mt-2 truncate">
                                                {item.media_file}
                                            </div>
                                        )}
                                        {item.folder && !item.media_file && (
                                            <div className="font-mono text-[11px] text-fg-dim mt-2 truncate">
                                                {item.folder}
                                            </div>
                                        )}
                                        {item.created_at && (
                                            <div className="text-[11px] text-fg-subtle mt-1.5">
                                                Added {formatDate(item.created_at)}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>

                    <Pagination
                        className="mt-2"
                        currentPage={Math.floor(filters.offset / filters.limit) + 1}
                        totalPages={Math.ceil(total / filters.limit)}
                        onPageChange={page =>
                            setFilters(prev => ({
                                ...prev,
                                offset: (page - 1) * prev.limit,
                            }))
                        }
                    />
                </>
            )}

            <Modal isOpen={!!deleteTarget} onClose={() => setDeleteTarget(null)} size="small">
                <Modal.Header>Delete Media Item</Modal.Header>
                <Modal.Body>
                    <p className="text-fg-muted">
                        Are you sure you want to delete{' '}
                        <span className="font-semibold text-fg">{deleteTarget?.title}</span>? This
                        action cannot be undone.
                    </p>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
                        Cancel
                    </Button>
                    <Button
                        variant="danger"
                        icon="delete"
                        onClick={handleDelete}
                        disabled={isDeleting}
                    >
                        {isDeleting ? 'Deleting...' : 'Delete'}
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default MediaSearchPage;
