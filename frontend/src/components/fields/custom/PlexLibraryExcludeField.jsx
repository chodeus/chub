/**
 * PlexLibraryExcludeField
 *
 * Poster Cleanarr library opt-out. Renders the Plex libraries (from the shared
 * catalog endpoint, scoped to the module's selected Plex instance when known)
 * as a checkbox list where a CHECKED library is EXCLUDED from the bloat pass.
 *
 * Value shape: string[] of excluded library names (matches the backend
 * `poster_cleanarr.excluded_libraries: List[str]`). Empty = nothing excluded
 * (every library in scope), which is the safe default. This is a display +
 * deletion-candidate deny-list only — the backend's in-use protection set is
 * always global, so opting a library out can never expose its live artwork to
 * deletion; at worst an excluded library's stale bloat is simply left alone.
 */

import React, { useMemo, useCallback, useId } from 'react';
import {
    FieldWrapper,
    FieldLabel,
    FieldError,
    FieldDescription,
    CheckboxBase,
} from '../primitives';
import { useApiData } from '../../../hooks/useApiData.js';
import { instancesAPI } from '../../../utils/api';

/** Plex instance names this module targets (poster_cleanarr stores List[str]). */
const selectedPlexNames = moduleConfig => {
    const raw = moduleConfig?.instances;
    if (!Array.isArray(raw)) return [];
    return raw
        .map(item => {
            if (typeof item === 'string') return item;
            if (item && typeof item === 'object') {
                if (item.instance || item.name) return item.instance || item.name;
                const keys = Object.keys(item);
                if (keys.length === 1) return keys[0];
            }
            return null;
        })
        .filter(Boolean);
};

export const PlexLibraryExcludeField = React.memo(
    ({
        field,
        value = [],
        onChange,
        moduleConfig,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
    }) => {
        const rawId = useId();
        const scopeId = `${rawId.replace(/[^A-Za-z0-9_-]/g, '')}-`;
        const inputId = `field-${field.key}`;
        const excluded = useMemo(() => (Array.isArray(value) ? value : []), [value]);

        const {
            data: catalogResponse,
            isLoading,
            error,
        } = useApiData({
            apiFunction: instancesAPI.fetchPlexCatalog,
            options: { immediate: true, showErrorToast: false },
        });

        // Flatten the catalog ({ instanceName: [{title,type,enabled}] }) to a
        // deduped, sorted list of library names. Scope to the module's selected
        // Plex instance(s) when set; otherwise show every instance's libraries.
        const libraries = useMemo(() => {
            const byInstance = catalogResponse?.data?.libraries;
            if (!byInstance || typeof byInstance !== 'object') return [];
            const wanted = selectedPlexNames(moduleConfig);
            const names = new Set();
            Object.entries(byInstance).forEach(([instanceName, list]) => {
                if (wanted.length && !wanted.includes(instanceName)) return;
                (Array.isArray(list) ? list : []).forEach(lib => {
                    if (typeof lib === 'string') {
                        if (lib) names.add(lib);
                    } else if (lib && typeof lib === 'object' && lib.title) {
                        names.add(lib.title);
                    }
                });
            });
            return Array.from(names).sort((a, b) => a.localeCompare(b));
        }, [catalogResponse, moduleConfig]);

        const toggle = useCallback(
            (name, checked) => {
                const current = Array.isArray(value) ? value : [];
                const next = checked ? [...current, name] : current.filter(n => n !== name);
                onChange(next);
            },
            [value, onChange]
        );

        // Preserve any excluded names no longer present in the catalog (e.g. a
        // renamed/removed library) so an unrelated toggle doesn't silently drop
        // them — surface them as checked-but-missing rows.
        const orphanedExcluded = useMemo(
            () => excluded.filter(n => !libraries.includes(n)),
            [excluded, libraries]
        );

        const body = () => {
            if (isLoading) {
                return (
                    <div className="flex items-center gap-3 p-4 text-sm text-fg-muted bg-surface-alt border border-border-subtle rounded-lg">
                        <div className="w-4 h-4 border-2 border-border border-t-primary rounded-full animate-spin" />
                        <span>Loading libraries…</span>
                    </div>
                );
            }
            if (error) {
                return (
                    <div className="flex items-center gap-3 p-4 text-sm text-error bg-surface border border-error rounded-lg">
                        <span className="text-base">⚠️</span>
                        <span>Failed to load Plex libraries</span>
                    </div>
                );
            }
            if (libraries.length === 0 && orphanedExcluded.length === 0) {
                return (
                    <div className="flex items-center gap-3 p-4 text-sm text-fg-muted bg-surface-alt border border-border-subtle rounded-lg">
                        <span className="text-base">ℹ️</span>
                        <span>
                            No Plex libraries found — select a Plex instance above, or check the
                            connection.
                        </span>
                    </div>
                );
            }
            const rows = [...libraries, ...orphanedExcluded];
            return (
                <div className="grid gap-2 grid-cols-1 md:grid-cols-2">
                    {rows.map(library => {
                        const isExcluded = excluded.includes(library);
                        const missing = orphanedExcluded.includes(library);
                        const libraryId = `${scopeId}exclude-lib-${library}`;
                        return (
                            <div
                                key={library}
                                className={`flex items-center gap-3 py-3 px-4 border rounded-lg cursor-pointer transition-all duration-200 ease-in-out ${
                                    isExcluded
                                        ? 'bg-primary/10 border-primary'
                                        : 'bg-surface border-border hover:bg-surface-hover hover:border-primary'
                                }`}
                                onClick={e => {
                                    if (disabled) return;
                                    if (
                                        e.target.tagName === 'LABEL' ||
                                        e.target.tagName === 'INPUT'
                                    )
                                        return;
                                    toggle(library, !isExcluded);
                                }}
                                role="button"
                                tabIndex={disabled ? -1 : 0}
                                onKeyDown={e => {
                                    if ((e.key === ' ' || e.key === 'Enter') && !disabled) {
                                        e.preventDefault();
                                        toggle(library, !isExcluded);
                                    }
                                }}
                                aria-pressed={isExcluded}
                                aria-disabled={disabled}
                            >
                                <CheckboxBase
                                    id={libraryId}
                                    name="cleanarr-excluded-libraries"
                                    checked={isExcluded}
                                    onChange={e => toggle(library, e.target.checked)}
                                    disabled={disabled}
                                />
                                <div className="flex flex-col flex-1 min-w-0">
                                    <FieldLabel
                                        htmlFor={libraryId}
                                        label={library}
                                        className="text-sm font-medium leading-normal text-fg cursor-pointer select-none truncate"
                                        title={library}
                                    />
                                    {missing && (
                                        <span className="text-xs text-fg-subtle">
                                            not in the current catalog — still excluded
                                        </span>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            );
        };

        return (
            <FieldWrapper invalid={highlightInvalid}>
                <FieldLabel label={field.label} helpText={field.helpText} />
                <div id={inputId} className="flex flex-col gap-2">
                    <div className="text-xs text-fg-subtle">
                        Checked libraries are skipped by Poster Cleanarr — their artwork is hidden
                        from the bloat view and never deleted. Leave all unchecked to scan every
                        library.
                    </div>
                    {body()}
                </div>
                {field.description && (
                    <FieldDescription id={`${inputId}-desc`} description={field.description} />
                )}
                {errorMessage && <FieldError id={`${inputId}-error`} message={errorMessage} />}
            </FieldWrapper>
        );
    }
);

PlexLibraryExcludeField.displayName = 'PlexLibraryExcludeField';

export default PlexLibraryExcludeField;
