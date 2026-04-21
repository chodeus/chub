/**
 * DirPickerField Component
 *
 * Interactive directory browser that uses systemAPI.listDirectory to browse
 * server-side directories and systemAPI.createDirectory to create new ones.
 */

import React, { useState, useCallback, useEffect } from 'react';
import { systemAPI } from '../../../utils/api/system.js';
import { FieldWrapper, FieldLabel, FieldDescription } from '../primitives';

export const DirPickerField = React.memo(({ field, value, onChange, disabled = false }) => {
    const [currentPath, setCurrentPath] = useState(value || '/');
    const [entries, setEntries] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [newDirName, setNewDirName] = useState('');
    const [creating, setCreating] = useState(false);

    const loadDirectory = useCallback(async path => {
        setLoading(true);
        setError(null);
        try {
            const result = await systemAPI.listDirectory(path);
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

    useEffect(() => {
        loadDirectory(currentPath);
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const handleNavigate = useCallback(
        dirName => {
            const newPath = currentPath === '/' ? `/${dirName}` : `${currentPath}/${dirName}`;
            loadDirectory(newPath);
        },
        [currentPath, loadDirectory]
    );

    const handleGoUp = useCallback(() => {
        const parts = currentPath.split('/').filter(Boolean);
        parts.pop();
        const parentPath = parts.length === 0 ? '/' : `/${parts.join('/')}`;
        loadDirectory(parentPath);
    }, [currentPath, loadDirectory]);

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
            loadDirectory(currentPath);
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

            {/* Current path display */}
            <div className="flex items-center gap-2 mb-2">
                <span className="text-xs text-secondary font-mono flex-1 truncate bg-surface-alt px-2 py-1 rounded">
                    {currentPath}
                </span>
                <button
                    type="button"
                    onClick={handleSelect}
                    disabled={disabled}
                    className="px-3 py-1 text-xs font-medium bg-primary/15 text-primary border border-primary/25 rounded cursor-pointer hover:bg-primary/25 disabled:opacity-50"
                >
                    Select
                </button>
            </div>

            {/* Directory listing */}
            <div className="border border-border rounded-lg max-h-48 overflow-y-auto bg-surface">
                {currentPath !== '/' && (
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
                    className="px-2 py-1 text-xs font-medium bg-surface-alt text-secondary border border-border rounded cursor-pointer hover:text-primary disabled:opacity-50"
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
