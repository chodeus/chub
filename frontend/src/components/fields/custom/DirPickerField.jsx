/**
 * DirPickerField Component
 *
 * Interactive directory browser that uses systemAPI.listDirectory to browse
 * server-side directories and systemAPI.createDirectory to create new ones.
 */

import React, { useState, useCallback, useEffect } from 'react';
import { systemAPI } from '../../../utils/api/system.js';
import { FieldWrapper, FieldLabel, FieldDescription } from '../primitives';

/**
 * Pick the allowed root that contains the given path (longest prefix wins).
 * Returns null if no root matches — the caller falls back to the first root.
 */
const matchRoot = (path, roots) => {
    if (!path || !Array.isArray(roots) || roots.length === 0) return null;
    let best = null;
    for (const r of roots) {
        if (path === r || path.startsWith(r + '/')) {
            if (!best || r.length > best.length) best = r;
        }
    }
    return best;
};

export const DirPickerField = React.memo(({ field, value, onChange, disabled = false }) => {
    const [currentPath, setCurrentPath] = useState(value || '');
    const [entries, setEntries] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [newDirName, setNewDirName] = useState('');
    const [creating, setCreating] = useState(false);
    // All allowed top-level roots fetched from /api/allowed-roots. Drives
    // the root selector dropdown.
    const [roots, setRoots] = useState([]);
    // The root the user is currently browsing under. "Go up" can't ascend
    // past this; changing the dropdown jumps to a different root.
    const [activeRoot, setActiveRoot] = useState(null);

    const loadDirectory = useCallback(async (path, { skipCache = false } = {}) => {
        setLoading(true);
        setError(null);
        try {
            // listDirectory caches results for 5 minutes by default. That's
            // fine for normal browsing but breaks the post-Create refresh —
            // the new folder won't appear until the cache expires. Callers
            // mutating the filesystem must pass skipCache: true.
            const result = await systemAPI.listDirectory(
                path,
                skipCache ? { useCache: false } : {}
            );
            const dirs = result?.data?.directories || result?.data || [];
            setEntries(Array.isArray(dirs) ? dirs : []);
            setCurrentPath(path);
        } catch (err) {
            setError(err.message || 'Failed to load directory');
            setEntries([]);
        } finally {
            setLoading(false);
        }
    }, []);

    // One-shot initialization: fetch allowed roots, decide which root we're
    // browsing under, and load the initial directory.
    useEffect(() => {
        let cancelled = false;
        systemAPI
            .listAllowedRoots()
            .then(result => {
                if (cancelled) return;
                const list = result?.data?.roots || [];
                if (list.length === 0) {
                    setError(
                        'No allowed directories configured. Set a source/destination path in another module first.'
                    );
                    return;
                }
                setRoots(list);
                // If the form already has a value, browse under whichever
                // root contains it; otherwise start at the first root.
                const startRoot = matchRoot(value, list) || list[0];
                setActiveRoot(startRoot);
                loadDirectory(value || startRoot);
            })
            .catch(err => {
                if (!cancelled) setError(err.message || 'Failed to load allowed directories');
            });
        return () => {
            cancelled = true;
        };
        // Init runs once; subsequent value changes from the parent are not
        // expected for the same instance (accordion remount creates a new one).
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handleNavigate = useCallback(
        dirName => {
            const newPath = currentPath === '/' ? `/${dirName}` : `${currentPath}/${dirName}`;
            loadDirectory(newPath);
        },
        [currentPath, loadDirectory]
    );

    const atRoot = !currentPath || currentPath === activeRoot;

    const handleGoUp = useCallback(() => {
        if (atRoot) return;
        const parts = currentPath.split('/').filter(Boolean);
        parts.pop();
        const parentPath = parts.length === 0 ? '/' : `/${parts.join('/')}`;
        loadDirectory(parentPath);
    }, [atRoot, currentPath, loadDirectory]);

    const handleRootChange = useCallback(
        e => {
            const newRoot = e.target.value;
            setActiveRoot(newRoot);
            loadDirectory(newRoot);
        },
        [loadDirectory]
    );

    const handleSelect = useCallback(() => {
        if (onChange) onChange(currentPath);
    }, [currentPath, onChange]);

    const handleCreateDir = useCallback(async () => {
        if (!newDirName.trim()) return;
        setCreating(true);
        try {
            const fullPath =
                currentPath === '/'
                    ? `/${newDirName.trim()}`
                    : `${currentPath}/${newDirName.trim()}`;
            await systemAPI.createDirectory(fullPath);
            setNewDirName('');
            // Skip the listDirectory cache so the just-created folder is
            // visible on the refresh — otherwise the user sees the old
            // listing for up to 5 minutes.
            loadDirectory(currentPath, { skipCache: true });
        } catch {
            setError('Failed to create directory');
        } finally {
            setCreating(false);
        }
    }, [newDirName, currentPath, loadDirectory]);

    const inputId = `field-${field.key}`;

    return (
        <FieldWrapper>
            <FieldLabel label={field.label} required={field.required} />

            {/* Root selector — only shown when there's more than one root to
                choose from, otherwise the picker behaves like before. */}
            {roots.length > 1 && (
                <div className="flex items-center gap-2 mb-2">
                    <label
                        htmlFor={`${inputId}-root`}
                        className="text-xs text-secondary whitespace-nowrap"
                    >
                        Root:
                    </label>
                    <select
                        id={`${inputId}-root`}
                        value={activeRoot || ''}
                        onChange={handleRootChange}
                        disabled={disabled || loading}
                        className="flex-1 px-2 py-1 text-xs bg-input border border-border rounded text-primary focus:border-primary focus:outline-none"
                    >
                        {roots.map(r => (
                            <option key={r} value={r}>
                                {r}
                            </option>
                        ))}
                    </select>
                </div>
            )}

            {/* Breadcrumb trail so users keep orientation in deep trees */}
            {currentPath && (
                <nav
                    className="mb-2 flex flex-wrap items-center gap-1 text-xs text-tertiary"
                    aria-label="Path breadcrumb"
                >
                    {(() => {
                        // Derive segments relative to activeRoot so users see
                        // "GDrive / posters / MM2K / Collection" rather than
                        // the full absolute path twice.
                        const rel =
                            activeRoot && currentPath.startsWith(activeRoot)
                                ? currentPath.slice(activeRoot.length)
                                : currentPath;
                        const parts = rel.split('/').filter(Boolean);
                        const crumbs = [
                            { name: activeRoot || '/', path: activeRoot || '/' },
                            ...parts.map((p, i) => ({
                                name: p,
                                path: `${activeRoot || ''}/${parts.slice(0, i + 1).join('/')}`,
                            })),
                        ];
                        return crumbs.map((c, i) => (
                            <React.Fragment key={c.path}>
                                {i > 0 && <span aria-hidden="true">/</span>}
                                <button
                                    type="button"
                                    onClick={() => loadDirectory(c.path)}
                                    disabled={disabled || loading || i === crumbs.length - 1}
                                    className="px-1.5 py-0.5 rounded hover:bg-surface-alt text-secondary disabled:text-primary disabled:font-medium disabled:cursor-default"
                                >
                                    {c.name}
                                </button>
                            </React.Fragment>
                        ));
                    })()}
                </nav>
            )}

            {/* Current path display — truncate-start keeps the leaf visible on
                narrow viewports so users see what they're about to select */}
            <div className="flex items-center gap-2 mb-2">
                <span
                    className="text-xs text-secondary font-mono flex-1 truncate truncate-start bg-surface-alt px-2 py-1 rounded"
                    title={currentPath}
                >
                    {currentPath}
                </span>
                <button
                    type="button"
                    onClick={handleSelect}
                    disabled={disabled || loading || !currentPath}
                    className="shrink-0 px-3 py-1 text-xs font-medium bg-primary/15 text-primary border border-primary/25 rounded cursor-pointer hover:bg-primary/25 disabled:opacity-50"
                >
                    Select
                </button>
            </div>

            {/* Directory listing */}
            <div className="border border-border rounded-lg max-h-48 overflow-y-auto bg-surface">
                {!atRoot && (
                    <button
                        type="button"
                        onClick={handleGoUp}
                        className="w-full text-left px-3 py-1.5 text-sm text-secondary hover:bg-surface-alt cursor-pointer border-b border-border flex items-center gap-2"
                    >
                        <span className="material-symbols-outlined text-base">arrow_upward</span>
                        ..
                    </button>
                )}
                {loading ? (
                    <div className="px-3 py-3 text-xs text-tertiary">Loading...</div>
                ) : error ? (
                    <div className="px-3 py-3 text-xs text-error">{error}</div>
                ) : entries.length === 0 ? (
                    <div className="px-3 py-3 text-xs text-tertiary">Empty directory</div>
                ) : (
                    entries.map(entry => {
                        const name = typeof entry === 'string' ? entry : entry.name;
                        return (
                            <button
                                key={name}
                                type="button"
                                onClick={() => handleNavigate(name)}
                                className="w-full text-left px-3 py-1.5 text-sm text-primary hover:bg-surface-alt cursor-pointer border-b border-border last:border-b-0 flex items-center gap-2"
                            >
                                <span className="material-symbols-outlined text-base text-secondary">
                                    folder
                                </span>
                                {name}
                            </button>
                        );
                    })
                )}
            </div>

            {/* Create new directory */}
            <div className="flex items-center gap-2 mt-2">
                <input
                    type="text"
                    value={newDirName}
                    onChange={e => setNewDirName(e.target.value)}
                    placeholder="New folder name..."
                    disabled={disabled || creating}
                    className="flex-1 px-2 py-1 text-sm bg-input border border-border rounded text-primary focus:border-primary focus:outline-none"
                    onKeyDown={e => {
                        if (e.key === 'Enter') handleCreateDir();
                    }}
                />
                <button
                    type="button"
                    onClick={handleCreateDir}
                    disabled={disabled || creating || !newDirName.trim()}
                    className="px-3 py-1.5 text-xs font-medium bg-primary text-on-color border border-primary rounded cursor-pointer hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed"
                >
                    {creating ? '...' : 'Create'}
                </button>
            </div>

            <FieldDescription id={`${inputId}-desc`} description={field.description} />
        </FieldWrapper>
    );
});

DirPickerField.displayName = 'DirPickerField';

export default DirPickerField;
