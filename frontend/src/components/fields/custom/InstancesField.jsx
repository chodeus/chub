/**
 * InstancesField Component
 *
 * Schema-driven instances selection field for CHUB service management.
 * Dynamically adapts behavior based on field configuration from settings_schema.js.
 *
 * Supported schema configurations:
 * 1. All services with poster option (poster_renamerr): ['plex', 'radarr', 'sonarr'] + add_posters_option: true
 * 2. ARR services only (renameinatorr, nohl): ['radarr', 'sonarr']
 * 3. Plex only (labelarr): ['plex'] + add_posters_option: false
 * 4. Health checks (health_checkarr): ['radarr', 'sonarr'] + add_posters_option: false
 * 5. Mixed configurations with different requirements
 *
 * Value Structure:
 * - Array of mixed strings and objects
 * - Simple instances: "instance_name"
 * - Plex with full options: { name: "instance_name", upload_posters: true/false, libraries: ["lib1", "lib2"] }
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
import { humanize } from '../../../utils/tools';
import Toggle from '../../ui/Toggle.jsx';

/** A boolean as the mock's label-left / toggle-right row (used for the
 *  plex_scope add-posters / match-collections options). */
const ToggleRow = ({ label, checked, disabled, onChange }) => (
    <div className="flex items-center justify-between gap-4 py-2.5 px-4 bg-surface-inset border border-border rounded-lg">
        <span className="text-sm font-medium text-fg">{label}</span>
        <Toggle label={label} checked={!!checked} disabled={disabled} onChange={onChange} />
    </div>
);

// Per-service dot colour for the instance pills (mirrors the design mock):
// Radarr green, Sonarr cyan, Lidarr/other lilac, Plex gold. The dot shows the
// service regardless of selection; selection is encoded by the pill's fill.
const SERVICE_DOT = {
    radarr: '#6cbc66',
    sonarr: '#53e8f0',
    lidarr: '#9a7ba9',
    readarr: '#9a7ba9',
    whisparr: '#9a7ba9',
    plex: '#ffc944',
};

/**
 * ARR instance pills — the *arr multi-select rendered as the design mock's
 * pill row (selected = brand fill, a service-colour dot on each). One row spans
 * all configured ARR service types. Toggling a pill emits a plain instance-name
 * string for that service type via onToggle(serviceType, name, checked) — the
 * exact same emit the previous checkbox UI used, so value shapes are unchanged.
 */
const ArrInstancePills = React.memo(
    ({ instances, arrTypes, selectedByType, onToggle, disabled }) => {
        const pills = useMemo(
            () => (instances || []).filter(i => arrTypes.includes(i.type)),
            [instances, arrTypes]
        );

        if (pills.length === 0) {
            return (
                <div className="text-sm text-fg-subtle bg-surface-inset border border-dashed border-border rounded-lg px-4 py-3">
                    No {arrTypes.map(humanize).join(' / ')} instances configured — add one in
                    Settings → Instances.
                </div>
            );
        }

        return (
            <div className="flex flex-wrap gap-2">
                {pills.map(instance => {
                    const isSelected = (selectedByType[instance.type] || []).includes(
                        instance.name
                    );
                    return (
                        <button
                            key={`${instance.type}-${instance.name}`}
                            type="button"
                            disabled={disabled}
                            onClick={() => onToggle(instance.type, instance.name, !isSelected)}
                            aria-pressed={isSelected}
                            title={instance.url || instance.name}
                            className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-[12.5px] font-medium border transition-colors cursor-pointer disabled:opacity-50 ${
                                isSelected
                                    ? 'bg-primary/15 border-primary text-fg'
                                    : 'bg-surface-inset border-border text-fg-muted hover:border-primary'
                            }`}
                        >
                            <span
                                className="w-1.5 h-1.5 rounded-full shrink-0"
                                style={{ background: SERVICE_DOT[instance.type] || '#8ea3cc' }}
                            />
                            {humanize(instance.name)}
                        </button>
                    );
                })}
            </div>
        );
    }
);

ArrInstancePills.displayName = 'ArrInstancePills';

/**
 * Plex Library Selector - Component for selecting libraries within a Plex instance
 * Handles library loading and selection for Plex instances
 */
const PlexLibrarySelector = React.memo(
    ({ instanceName, selectedLibraries = [], onLibrariesChange, disabled, scopeId = '' }) => {
        // Load libraries for this specific Plex instance
        const {
            data: librariesResponse,
            isLoading: librariesLoading,
            error: librariesError,
        } = useApiData({
            apiFunction: () => instancesAPI.fetchPlexLibraries(instanceName),
            dependencies: [instanceName],
            options: {
                immediate: true,
                showErrorToast: false, // Don't show toast for library loading errors
            },
        });

        // Extract libraries from API response and categorize them.
        //
        // The /plex/{instance}/libraries endpoint returns objects of shape
        // `{title, type}` where `type` is the authoritative Plex section type
        // (movie / show / artist / photo). We bucket by `type` so that a user
        // who renames their movie library to "Cinema" still sees it under the
        // Movies group.
        //
        // Legacy responses (plain strings) and any stale 10-min-TTL cache
        // entries shaped that way are tolerated via a substring fallback so a
        // mid-deploy reload does not break the UI.
        const { movieLibraries, tvLibraries, uncategorizedLibraries } = useMemo(() => {
            const librariesData = librariesResponse?.data?.libraries;
            if (!librariesData || !Array.isArray(librariesData)) {
                return { movieLibraries: [], tvLibraries: [], uncategorizedLibraries: [] };
            }

            const movies = [];
            const tv = [];
            const uncategorized = [];

            librariesData.forEach(library => {
                if (!library) return;
                // Respect the instance-level opt-in: a library the user has not
                // enabled must never appear in a module picker (the list/catalog
                // endpoints annotate each library with `enabled`).
                if (typeof library === 'object' && library.enabled === false) return;

                let title;
                let type;
                if (typeof library === 'string') {
                    // Legacy / stale-cache shape: bucket by title substring.
                    title = library;
                    const lowerName = title.toLowerCase();
                    if (lowerName.includes('movie') || lowerName.includes('film')) {
                        type = 'movie';
                    } else if (
                        lowerName.includes('series') ||
                        lowerName.includes('show') ||
                        lowerName.includes('tv')
                    ) {
                        type = 'show';
                    } else {
                        type = '';
                    }
                } else if (typeof library === 'object' && library.title) {
                    title = library.title;
                    type = (library.type || '').toLowerCase();
                } else {
                    return; // Skip invalid entries
                }

                if (type === 'movie') {
                    movies.push(title);
                } else if (type === 'show') {
                    tv.push(title);
                } else {
                    uncategorized.push(title);
                }
            });

            return {
                movieLibraries: movies,
                tvLibraries: tv,
                uncategorizedLibraries: uncategorized,
            };
        }, [librariesResponse]);

        // Handle library selection toggle
        const handleLibraryToggle = useCallback(
            (libraryName, checked) => {
                const currentLibraries = selectedLibraries || [];
                const newLibraries = checked
                    ? [...currentLibraries, libraryName]
                    : currentLibraries.filter(lib => lib !== libraryName);
                onLibrariesChange(newLibraries);
            },
            [selectedLibraries, onLibrariesChange]
        );

        if (librariesLoading) {
            return (
                <div className="flex items-center gap-3 p-4 text-sm text-fg-muted bg-surface-alt border border-border-subtle rounded-lg">
                    <div className="w-4 h-4 border-2 border-border border-t-primary rounded-full animate-spin" />
                    <span>Loading libraries...</span>
                </div>
            );
        }

        if (librariesError) {
            return (
                <div className="flex items-center gap-3 p-4 text-sm text-error bg-surface border border-error rounded-lg">
                    <span className="text-base">⚠️</span>
                    <span>Failed to load libraries: {librariesError.message}</span>
                </div>
            );
        }

        const totalLibraries =
            movieLibraries.length + tvLibraries.length + uncategorizedLibraries.length;
        if (totalLibraries === 0) {
            return (
                <div className="flex items-center gap-3 p-4 text-sm text-fg-muted bg-surface-alt border border-border-subtle rounded-lg">
                    <span className="text-base">ℹ️</span>
                    <span>No libraries found for this Plex instance</span>
                </div>
            );
        }

        return (
            <div>
                <div className="text-base font-semibold text-fg mb-3 pb-2 border-b border-border-subtle">
                    Select Libraries
                </div>

                {/* Mobile: Compact chip-style selection */}
                <div className="md:hidden">
                    {movieLibraries.length > 0 && (
                        <div className="mb-4">
                            <div className="text-sm font-medium text-fg mb-2">Movies</div>
                            <div className="grid gap-2 grid-cols-auto-fit-xs">
                                {movieLibraries.map(library => {
                                    const isSelected = selectedLibraries.includes(library);
                                    return (
                                        <button
                                            key={library}
                                            type="button"
                                            className={`relative flex items-center justify-center text-center py-2 px-3 min-h-11 rounded-lg border-2 text-sm font-medium cursor-pointer transition-all duration-200 truncate ${
                                                isSelected
                                                    ? 'bg-surface border-primary text-fg shadow-md scale-105'
                                                    : 'bg-surface-elevated border-border text-fg hover:bg-surface-hover hover:border-primary hover:-translate-y-0.5 hover:shadow-sm'
                                            }`}
                                            onClick={() =>
                                                handleLibraryToggle(library, !isSelected)
                                            }
                                            disabled={disabled}
                                            title={library}
                                        >
                                            {library}
                                            {isSelected && (
                                                <span className="absolute top-0.5 right-1 text-xs">
                                                    ✓
                                                </span>
                                            )}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {tvLibraries.length > 0 && (
                        <div className="mb-4">
                            <div className="text-sm font-medium text-fg mb-2">TV Shows</div>
                            <div className="grid gap-2 grid-cols-auto-fit-xs">
                                {tvLibraries.map(library => {
                                    const isSelected = selectedLibraries.includes(library);
                                    return (
                                        <button
                                            key={library}
                                            type="button"
                                            className={`relative flex items-center justify-center text-center py-2 px-3 min-h-11 rounded-lg border-2 text-sm font-medium cursor-pointer transition-all duration-200 truncate ${
                                                isSelected
                                                    ? 'bg-surface border-primary text-fg shadow-md scale-105'
                                                    : 'bg-surface-elevated border-border text-fg hover:bg-surface-hover hover:border-primary hover:-translate-y-0.5 hover:shadow-sm'
                                            }`}
                                            onClick={() =>
                                                handleLibraryToggle(library, !isSelected)
                                            }
                                            disabled={disabled}
                                            title={library}
                                        >
                                            {library}
                                            {isSelected && (
                                                <span className="absolute top-0.5 right-1 text-xs">
                                                    ✓
                                                </span>
                                            )}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {uncategorizedLibraries.length > 0 && (
                        <div>
                            <div className="text-sm font-medium text-fg mb-2">Other</div>
                            <div className="grid gap-2 grid-cols-auto-fit-xs">
                                {uncategorizedLibraries.map(library => {
                                    const isSelected = selectedLibraries.includes(library);
                                    return (
                                        <button
                                            key={library}
                                            type="button"
                                            className={`relative flex items-center justify-center text-center py-2 px-3 min-h-11 rounded-lg border-2 text-sm font-medium cursor-pointer transition-all duration-200 truncate ${
                                                isSelected
                                                    ? 'bg-surface border-primary text-fg shadow-md scale-105'
                                                    : 'bg-surface-elevated border-border text-fg hover:bg-surface-hover hover:border-primary hover:-translate-y-0.5 hover:shadow-sm'
                                            }`}
                                            onClick={() =>
                                                handleLibraryToggle(library, !isSelected)
                                            }
                                            disabled={disabled}
                                            title={library}
                                        >
                                            {library}
                                            {isSelected && (
                                                <span className="absolute top-0.5 right-1 text-xs">
                                                    ✓
                                                </span>
                                            )}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>

                {/* Desktop: Grid layout with checkboxes */}
                <div className="max-md:hidden">
                    {movieLibraries.length > 0 && (
                        <div className="mb-6">
                            <div className="text-sm font-semibold text-fg mb-3 pb-1 border-b border-border">
                                Movies
                            </div>
                            <div className="grid gap-3 grid-cols-2">
                                {movieLibraries.map(library => {
                                    const isSelected = selectedLibraries.includes(library);
                                    const libraryId = `${scopeId}library-${instanceName}-${library}`;

                                    return (
                                        <div key={library}>
                                            <div
                                                className="flex items-center gap-3 py-3 px-4 bg-surface border border-border rounded-lg hover:bg-surface-hover hover:border-primary hover:shadow-sm focus:border-primary cursor-pointer transition-all duration-200 ease-in-out"
                                                onClick={e => {
                                                    // Don't handle click if it came from the label or checkbox input
                                                    if (disabled) return;
                                                    if (
                                                        e.target.tagName === 'LABEL' ||
                                                        e.target.tagName === 'INPUT'
                                                    )
                                                        return;
                                                    handleLibraryToggle(library, !isSelected);
                                                }}
                                                role="button"
                                                tabIndex={disabled ? -1 : 0}
                                                onKeyDown={e => {
                                                    if (
                                                        (e.key === ' ' || e.key === 'Enter') &&
                                                        !disabled
                                                    ) {
                                                        e.preventDefault();
                                                        handleLibraryToggle(library, !isSelected);
                                                    }
                                                }}
                                                aria-pressed={isSelected}
                                                aria-disabled={disabled}
                                            >
                                                <CheckboxBase
                                                    id={libraryId}
                                                    name={`${instanceName}-libraries`}
                                                    checked={isSelected}
                                                    onChange={e =>
                                                        handleLibraryToggle(
                                                            library,
                                                            e.target.checked
                                                        )
                                                    }
                                                    disabled={disabled}
                                                />
                                                <div className="flex flex-col flex-1 min-w-0">
                                                    <FieldLabel
                                                        htmlFor={libraryId}
                                                        label={library}
                                                        className="text-sm font-medium leading-normal text-fg cursor-pointer select-none truncate"
                                                        title={library}
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {tvLibraries.length > 0 && (
                        <div className="mb-6">
                            <div className="text-sm font-semibold text-fg mb-3 pb-1 border-b border-border">
                                TV Shows
                            </div>
                            <div className="grid gap-3 grid-cols-2">
                                {tvLibraries.map(library => {
                                    const isSelected = selectedLibraries.includes(library);
                                    const libraryId = `${scopeId}library-${instanceName}-${library}`;

                                    return (
                                        <div key={library}>
                                            <div
                                                className="flex items-center gap-3 py-3 px-4 bg-surface border border-border rounded-lg hover:bg-surface-hover hover:border-primary hover:shadow-sm focus:border-primary cursor-pointer transition-all duration-200 ease-in-out"
                                                onClick={e => {
                                                    // Don't handle click if it came from the label or checkbox input
                                                    if (disabled) return;
                                                    if (
                                                        e.target.tagName === 'LABEL' ||
                                                        e.target.tagName === 'INPUT'
                                                    )
                                                        return;
                                                    handleLibraryToggle(library, !isSelected);
                                                }}
                                                role="button"
                                                tabIndex={disabled ? -1 : 0}
                                                onKeyDown={e => {
                                                    if (
                                                        (e.key === ' ' || e.key === 'Enter') &&
                                                        !disabled
                                                    ) {
                                                        e.preventDefault();
                                                        handleLibraryToggle(library, !isSelected);
                                                    }
                                                }}
                                                aria-pressed={isSelected}
                                                aria-disabled={disabled}
                                            >
                                                <CheckboxBase
                                                    id={libraryId}
                                                    name={`${instanceName}-libraries`}
                                                    checked={isSelected}
                                                    onChange={e =>
                                                        handleLibraryToggle(
                                                            library,
                                                            e.target.checked
                                                        )
                                                    }
                                                    disabled={disabled}
                                                />
                                                <div className="flex flex-col flex-1 min-w-0">
                                                    <FieldLabel
                                                        htmlFor={libraryId}
                                                        label={library}
                                                        className="text-sm font-medium leading-normal text-fg cursor-pointer select-none truncate"
                                                        title={library}
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {uncategorizedLibraries.length > 0 && (
                        <div>
                            <div className="text-sm font-semibold text-fg mb-3 pb-1 border-b border-border">
                                Other
                            </div>
                            <div className="grid gap-3 grid-cols-2">
                                {uncategorizedLibraries.map(library => {
                                    const isSelected = selectedLibraries.includes(library);
                                    const libraryId = `${scopeId}library-${instanceName}-${library}`;

                                    return (
                                        <div key={library}>
                                            <div
                                                className="flex items-center gap-3 py-3 px-4 bg-surface border border-border rounded-lg hover:bg-surface-hover hover:border-primary hover:shadow-sm focus:border-primary cursor-pointer transition-all duration-200 ease-in-out"
                                                onClick={e => {
                                                    // Don't handle click if it came from the label or checkbox input
                                                    if (disabled) return;
                                                    if (
                                                        e.target.tagName === 'LABEL' ||
                                                        e.target.tagName === 'INPUT'
                                                    )
                                                        return;
                                                    handleLibraryToggle(library, !isSelected);
                                                }}
                                                role="button"
                                                tabIndex={disabled ? -1 : 0}
                                                onKeyDown={e => {
                                                    if (
                                                        (e.key === ' ' || e.key === 'Enter') &&
                                                        !disabled
                                                    ) {
                                                        e.preventDefault();
                                                        handleLibraryToggle(library, !isSelected);
                                                    }
                                                }}
                                                aria-pressed={isSelected}
                                                aria-disabled={disabled}
                                            >
                                                <CheckboxBase
                                                    id={libraryId}
                                                    name={`${instanceName}-libraries`}
                                                    checked={isSelected}
                                                    onChange={e =>
                                                        handleLibraryToggle(
                                                            library,
                                                            e.target.checked
                                                        )
                                                    }
                                                    disabled={disabled}
                                                />
                                                <div className="flex flex-col flex-1 min-w-0">
                                                    <FieldLabel
                                                        htmlFor={libraryId}
                                                        label={library}
                                                        className="text-sm font-medium leading-normal text-fg cursor-pointer select-none truncate"
                                                        title={library}
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        );
    }
);

PlexLibrarySelector.displayName = 'PlexLibrarySelector';

/**
 * Plex Instance Selector - For Plex instances with libraries and optional poster upload
 * Handles complex object values with upload_posters boolean and libraries array
 */
const PlexInstanceSelector = React.memo(
    ({
        instances,
        selectedInstances,
        onSelectionChange,
        showPosterOption,
        disabled,
        valueFormat = 'object',
        scopeId = '',
    }) => {
        const plexInstances = useMemo(() => {
            if (!instances || !Array.isArray(instances)) {
                return [];
            }
            return instances.filter(instance => instance.type === 'plex');
        }, [instances]);

        // Modules whose backend stores `instances: List[str]` (poster_cleanarr,
        // unmatched_assets, etc.) need plain strings; the library/add_posters UI
        // doesn't apply. valueFormat='string' disables both.
        const emitAsString = valueFormat === 'string';

        // Parse selected instances to handle both string and object formats
        // Normalizes to backend-compatible format: { instance, add_posters, library_names }
        const parsedSelection = useMemo(() => {
            if (!selectedInstances || !Array.isArray(selectedInstances)) {
                return [];
            }
            return selectedInstances.map(item => {
                if (typeof item === 'string') {
                    return { instance: item, add_posters: false, library_names: [] };
                }
                if (typeof item === 'object' && (item.instance || item.name)) {
                    return {
                        instance: item.instance || item.name,
                        add_posters: item.add_posters || item.upload_posters || false,
                        library_names: item.library_names || item.libraries || [],
                    };
                }
                if (typeof item === 'object' && !item.instance && !item.name) {
                    // Handle config format: {plex_1: {library_names: [...], add_posters: true}}
                    const entries = Object.entries(item);
                    if (entries.length > 0) {
                        const [plexName, plexConfig] = entries[0];
                        return {
                            instance: plexName,
                            add_posters: plexConfig?.add_posters || false,
                            library_names: plexConfig?.library_names || [],
                        };
                    }
                }
                return { instance: 'unknown', add_posters: false, library_names: [] };
            });
        }, [selectedInstances]);

        // Items reach this component in three shapes — plain string, the
        // {instance, add_posters, library_names} object the form emits on
        // first-toggle, and the config-style {plex_name: {library_names,
        // add_posters}} dict that PosterRenamerrConfig stores on disk.
        // All three handlers below need to identify items by instance name
        // regardless of which shape they're in, otherwise toggles silently
        // no-op on config-loaded data.
        const getItemName = item => {
            if (typeof item === 'string') return item;
            if (typeof item !== 'object' || item === null) return null;
            if (item.instance || item.name) return item.instance || item.name;
            const keys = Object.keys(item);
            return keys.length === 1 ? keys[0] : null;
        };

        const getItemAddPosters = item => {
            if (typeof item !== 'object' || item === null) return false;
            if (item.instance || item.name) {
                return item.add_posters || item.upload_posters || false;
            }
            const keys = Object.keys(item);
            if (keys.length === 1) return item[keys[0]]?.add_posters || false;
            return false;
        };

        const getItemLibraries = item => {
            if (typeof item !== 'object' || item === null) return [];
            if (item.instance || item.name) {
                return item.library_names || item.libraries || [];
            }
            const keys = Object.keys(item);
            if (keys.length === 1) return item[keys[0]]?.library_names || [];
            return [];
        };

        // Emit shape depends on the backend pydantic model:
        //   showPosterOption=true  → poster_renamerr expects
        //     List[Union[str, Dict[plex_name, {library_names, add_posters}]]]
        //     (config-style dict keyed by instance name)
        //   showPosterOption=false → labelarr / nestarr expect
        //     List[{instance, library_names}] (object-with-instance)
        // The wrong shape silently round-trips to empty values or rejects on
        // ChubConfig.model_validate, so this distinction matters.
        const buildPlexItem = (instanceName, libraries, addPosters) =>
            showPosterOption
                ? {
                      [instanceName]: {
                          library_names: libraries,
                          add_posters: addPosters,
                      },
                  }
                : { instance: instanceName, library_names: libraries };

        const handleInstanceToggle = useCallback(
            (instanceName, checked) => {
                if (checked) {
                    // For simple-list modules, emit a plain string so the backend's
                    // List[str] pydantic model accepts the payload.
                    const newInstance = emitAsString
                        ? instanceName
                        : buildPlexItem(instanceName, [], false);
                    onSelectionChange([...(selectedInstances || []), newInstance]);
                } else {
                    // Remove instance — match across all three item shapes.
                    const newSelection = (selectedInstances || []).filter(
                        item => getItemName(item) !== instanceName
                    );
                    onSelectionChange(newSelection);
                }
            },
            // eslint-disable-next-line react-hooks/exhaustive-deps
            [selectedInstances, onSelectionChange, showPosterOption, emitAsString]
        );

        const handlePosterUploadToggle = useCallback(
            (instanceName, addPosters) => {
                const newSelection = (selectedInstances || []).map(item => {
                    if (getItemName(item) !== instanceName) return item;
                    return buildPlexItem(instanceName, getItemLibraries(item), addPosters);
                });
                onSelectionChange(newSelection);
            },
            // eslint-disable-next-line react-hooks/exhaustive-deps
            [selectedInstances, onSelectionChange, showPosterOption]
        );

        const handleLibrariesChange = useCallback(
            (instanceName, libraries) => {
                const newSelection = (selectedInstances || []).map(item => {
                    if (getItemName(item) !== instanceName) return item;
                    return buildPlexItem(instanceName, libraries, getItemAddPosters(item));
                });
                onSelectionChange(newSelection);
            },
            // eslint-disable-next-line react-hooks/exhaustive-deps
            [selectedInstances, onSelectionChange, showPosterOption]
        );

        if (plexInstances.length === 0) {
            return (
                <div className="flex flex-col items-center gap-3 p-6 text-center bg-surface border border-dashed rounded-lg text-fg-muted">
                    <div className="font-medium text-fg">No Plex instances configured</div>
                    <div className="text-sm text-fg-subtle">
                        Configure instances in Settings → Instances
                    </div>
                </div>
            );
        }

        return (
            <div className="flex flex-col gap-2">
                {plexInstances.map(instance => {
                    const selectedItem = parsedSelection.find(
                        item => item.instance === instance.name
                    );
                    const isSelected = Boolean(selectedItem);
                    const uploadPosters = selectedItem?.add_posters || false;
                    const selectedLibraries = selectedItem?.library_names || [];
                    const instanceId = `${scopeId}instance-plex-${instance.name}`;
                    const uploadId = `${scopeId}upload-${instance.name}`;

                    return (
                        <div key={instance.name}>
                            <div
                                className="flex items-center gap-3 py-3 px-4 bg-surface border border-border rounded-lg hover:bg-surface-hover hover:border-primary hover:shadow-sm focus:border-primary cursor-pointer transition-all duration-200 ease-in-out"
                                onClick={e => {
                                    // Don't handle click if it came from the label or checkbox input
                                    if (disabled) return;
                                    if (
                                        e.target.tagName === 'LABEL' ||
                                        e.target.tagName === 'INPUT'
                                    )
                                        return;
                                    handleInstanceToggle(instance.name, !isSelected);
                                }}
                                role="button"
                                tabIndex={disabled ? -1 : 0}
                                onKeyDown={e => {
                                    if ((e.key === ' ' || e.key === 'Enter') && !disabled) {
                                        e.preventDefault();
                                        handleInstanceToggle(instance.name, !isSelected);
                                    }
                                }}
                                aria-pressed={isSelected}
                                aria-disabled={disabled}
                            >
                                <CheckboxBase
                                    id={instanceId}
                                    name="plex-instances"
                                    checked={isSelected}
                                    onChange={e =>
                                        handleInstanceToggle(instance.name, e.target.checked)
                                    }
                                    disabled={disabled}
                                />
                                <div className="flex flex-col">
                                    <FieldLabel
                                        htmlFor={instanceId}
                                        label={humanize(instance.name)}
                                        className="text-sm font-normal leading-normal text-fg cursor-pointer select-none"
                                    />
                                    {instance.url && (
                                        <div className="text-xs text-fg-muted">{instance.url}</div>
                                    )}
                                </div>
                            </div>

                            {isSelected && !emitAsString && (
                                <div className="flex flex-col gap-4 border-l-2 border-border-subtle">
                                    {/* Poster upload option */}
                                    {showPosterOption && (
                                        <div>
                                            <div
                                                className="flex items-center gap-3 py-3 px-4 bg-surface border border-border rounded-lg hover:bg-surface-hover hover:border-primary hover:shadow-sm focus:border-primary cursor-pointer transition-all duration-200 ease-in-out"
                                                onClick={e => {
                                                    // Don't handle click if it came from the label or checkbox input
                                                    if (disabled) return;
                                                    if (
                                                        e.target.tagName === 'LABEL' ||
                                                        e.target.tagName === 'INPUT'
                                                    )
                                                        return;
                                                    handlePosterUploadToggle(
                                                        instance.name,
                                                        !uploadPosters
                                                    );
                                                }}
                                                role="button"
                                                tabIndex={disabled ? -1 : 0}
                                                onKeyDown={e => {
                                                    if (
                                                        (e.key === ' ' || e.key === 'Enter') &&
                                                        !disabled
                                                    ) {
                                                        e.preventDefault();
                                                        handlePosterUploadToggle(
                                                            instance.name,
                                                            !uploadPosters
                                                        );
                                                    }
                                                }}
                                                aria-pressed={uploadPosters}
                                                aria-disabled={disabled}
                                            >
                                                <CheckboxBase
                                                    id={uploadId}
                                                    name={`upload-${instance.name}`}
                                                    checked={uploadPosters}
                                                    onChange={e =>
                                                        handlePosterUploadToggle(
                                                            instance.name,
                                                            e.target.checked
                                                        )
                                                    }
                                                    disabled={disabled}
                                                />
                                                <div className="flex flex-col">
                                                    <FieldLabel
                                                        htmlFor={uploadId}
                                                        label="Upload to this Plex instance"
                                                        className="text-sm font-medium leading-normal text-fg cursor-pointer select-none"
                                                    />
                                                    <span className="text-xs text-fg-subtle">
                                                        Only used when this module&apos;s Apply
                                                        Method is set to Plex.
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    {/* Library selection */}
                                    <PlexLibrarySelector
                                        instanceName={instance.name}
                                        selectedLibraries={selectedLibraries}
                                        onLibrariesChange={libraries =>
                                            handleLibrariesChange(instance.name, libraries)
                                        }
                                        disabled={disabled}
                                        scopeId={scopeId}
                                    />
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        );
    }
);

PlexInstanceSelector.displayName = 'PlexInstanceSelector';

/**
 * PlexScopeLibrarySelector - Library picker driven by the catalog endpoint.
 * Falls back to per-instance fetchPlexLibraries if catalog data is absent.
 */
const PlexScopeLibrarySelector = React.memo(
    ({
        instanceName,
        catalogLibraries,
        selectedLibraries = [],
        onLibrariesChange,
        disabled,
        scopeId = '',
    }) => {
        const hasCatalogData =
            catalogLibraries !== null &&
            catalogLibraries !== undefined &&
            Array.isArray(catalogLibraries);

        const {
            data: perInstanceResponse,
            isLoading: perInstanceLoading,
            error: perInstanceError,
        } = useApiData({
            apiFunction: () => instancesAPI.fetchPlexLibraries(instanceName),
            dependencies: [instanceName],
            options: {
                immediate: !hasCatalogData,
                showErrorToast: false,
            },
        });

        const allLibraries = useMemo(() => {
            const raw = hasCatalogData ? catalogLibraries : perInstanceResponse?.data?.libraries;
            if (!raw || !Array.isArray(raw)) return [];
            // Only opted-in libraries are selectable — a de-selected library
            // (annotated enabled:false by the backend) is hidden here too.
            return raw
                .filter(lib => typeof lib === 'string' || lib.enabled !== false)
                .map(lib => (typeof lib === 'string' ? lib : lib.title || ''))
                .filter(Boolean);
        }, [hasCatalogData, catalogLibraries, perInstanceResponse]);

        const handleToggle = useCallback(
            (libraryName, checked) => {
                const current = selectedLibraries || [];
                const updated = checked
                    ? [...current, libraryName]
                    : current.filter(l => l !== libraryName);
                onLibrariesChange(updated);
            },
            [selectedLibraries, onLibrariesChange]
        );

        if (!hasCatalogData && perInstanceLoading) {
            return (
                <div className="flex items-center gap-3 p-4 text-sm text-fg-muted bg-surface-alt border border-border-subtle rounded-lg">
                    <div className="w-4 h-4 border-2 border-border border-t-primary rounded-full animate-spin" />
                    <span>Loading libraries...</span>
                </div>
            );
        }

        if (!hasCatalogData && perInstanceError) {
            return (
                <div className="flex items-center gap-3 p-4 text-sm text-error bg-surface border border-error rounded-lg">
                    <span className="text-base">⚠️</span>
                    <span>Failed to load libraries</span>
                </div>
            );
        }

        if (allLibraries.length === 0) {
            return (
                <div className="flex items-center gap-3 p-4 text-sm text-fg-muted bg-surface-alt border border-border-subtle rounded-lg">
                    <span className="text-base">ℹ️</span>
                    <span>No enabled libraries — opt some in on Settings → Instances</span>
                </div>
            );
        }

        return (
            <div>
                <div className="text-sm font-semibold text-fg mb-2 pb-1 border-b border-border-subtle">
                    Libraries{' '}
                    <span className="text-xs font-normal text-fg-subtle">
                        (empty = all enabled)
                    </span>
                </div>
                <div className="grid gap-2 grid-cols-1 md:grid-cols-2">
                    {allLibraries.map(library => {
                        const isSelected = selectedLibraries.includes(library);
                        const libraryId = `${scopeId}scope-lib-${instanceName}-${library}`;
                        return (
                            <div key={library}>
                                <div
                                    className="flex items-center gap-3 py-3 px-4 bg-surface border border-border rounded-lg hover:bg-surface-hover hover:border-primary hover:shadow-sm cursor-pointer transition-all duration-200 ease-in-out"
                                    onClick={e => {
                                        if (disabled) return;
                                        if (
                                            e.target.tagName === 'LABEL' ||
                                            e.target.tagName === 'INPUT'
                                        )
                                            return;
                                        handleToggle(library, !isSelected);
                                    }}
                                    role="button"
                                    tabIndex={disabled ? -1 : 0}
                                    onKeyDown={e => {
                                        if ((e.key === ' ' || e.key === 'Enter') && !disabled) {
                                            e.preventDefault();
                                            handleToggle(library, !isSelected);
                                        }
                                    }}
                                    aria-pressed={isSelected}
                                    aria-disabled={disabled}
                                >
                                    <CheckboxBase
                                        id={libraryId}
                                        name={`${instanceName}-scope-libraries`}
                                        checked={isSelected}
                                        onChange={e => handleToggle(library, e.target.checked)}
                                        disabled={disabled}
                                    />
                                    <div className="flex flex-col flex-1 min-w-0">
                                        <FieldLabel
                                            htmlFor={libraryId}
                                            label={library}
                                            className="text-sm font-medium leading-normal text-fg cursor-pointer select-none truncate"
                                            title={library}
                                        />
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        );
    }
);

PlexScopeLibrarySelector.displayName = 'PlexScopeLibrarySelector';

/**
 * buildPlexScopeItem - Creates a flat plex_scope entry.
 */
const buildPlexScopeItem = (instanceName, libraries, addPosters, matchCollections) => ({
    instance: instanceName,
    library_names: libraries,
    add_posters: addPosters,
    match_collections: matchCollections,
});

/**
 * parsePlexScopeValue - Normalises incoming value to flat plex_scope shape.
 * Tolerates:
 *   - Array<{instance, library_names, add_posters, match_collections}>  (canonical)
 *   - Array<{name:{library_names, add_posters, ...}}>                   (legacy dict)
 *   - Array<string>                                                       (bare names)
 */
const parsePlexScopeValue = items => {
    if (!Array.isArray(items)) return [];
    return items
        .map(item => {
            if (typeof item === 'string') {
                return buildPlexScopeItem(item, [], false, false);
            }
            if (typeof item === 'object' && item !== null) {
                if (item.instance) {
                    return buildPlexScopeItem(
                        item.instance,
                        item.library_names || [],
                        item.add_posters || false,
                        item.match_collections || false
                    );
                }
                if (item.name) {
                    return buildPlexScopeItem(
                        item.name,
                        item.library_names || item.libraries || [],
                        item.add_posters || item.upload_posters || false,
                        item.match_collections || false
                    );
                }
                // Legacy dict shape: {plex_1: {library_names, add_posters}}
                const keys = Object.keys(item);
                if (keys.length === 1) {
                    const cfg = item[keys[0]] || {};
                    return buildPlexScopeItem(
                        keys[0],
                        cfg.library_names || [],
                        cfg.add_posters || false,
                        cfg.match_collections || false
                    );
                }
            }
            return null;
        })
        .filter(Boolean);
};

/**
 * PlexScopeSelector - Renders plex_scope field.
 * Emits Array<{instance, library_names, add_posters, match_collections}>.
 * Library data comes from the catalog endpoint; falls back per-instance.
 */
const PlexScopeSelector = React.memo(
    ({
        instances,
        value,
        onChange,
        showAddPosters,
        showMatchCollections,
        disabled,
        scopeId = '',
    }) => {
        const plexInstances = useMemo(
            () => (instances || []).filter(inst => inst.type === 'plex'),
            [instances]
        );

        const { data: catalogResponse, isLoading: catalogLoading } = useApiData({
            apiFunction: instancesAPI.fetchPlexCatalog,
            options: { immediate: true, showErrorToast: false },
        });

        // catalog.data.libraries = { instanceName: [{title, type}] }
        const catalogByInstance = useMemo(() => {
            const libs = catalogResponse?.data?.libraries;
            if (!libs || typeof libs !== 'object') return {};
            const result = {};
            Object.entries(libs).forEach(([name, list]) => {
                result[name] = Array.isArray(list) ? list : [];
            });
            return result;
        }, [catalogResponse]);

        const parsedValue = useMemo(() => parsePlexScopeValue(value), [value]);

        const getEntry = useCallback(
            instanceName => parsedValue.find(e => e.instance === instanceName) || null,
            [parsedValue]
        );

        const handleInstanceToggle = useCallback(
            (instanceName, checked) => {
                if (checked) {
                    onChange([...parsedValue, buildPlexScopeItem(instanceName, [], false, false)]);
                } else {
                    onChange(parsedValue.filter(e => e.instance !== instanceName));
                }
            },
            [parsedValue, onChange]
        );

        const updateEntry = useCallback(
            (instanceName, patch) => {
                onChange(
                    parsedValue.map(e => (e.instance === instanceName ? { ...e, ...patch } : e))
                );
            },
            [parsedValue, onChange]
        );

        if (plexInstances.length === 0) {
            return (
                <div className="flex flex-col items-center gap-3 p-6 text-center bg-surface border border-dashed rounded-lg text-fg-muted">
                    <div className="font-medium text-fg">No Plex instances configured</div>
                    <div className="text-sm text-fg-subtle">
                        Configure instances in Settings → Instances
                    </div>
                </div>
            );
        }

        return (
            <div className="flex flex-col gap-2">
                {plexInstances.map(instance => {
                    const entry = getEntry(instance.name);
                    const isSelected = Boolean(entry);
                    const instanceId = `${scopeId}scope-inst-${instance.name}`;

                    // Catalog libraries for this instance (null while loading = fallback)
                    const catalogLibs = catalogLoading
                        ? null
                        : (catalogByInstance[instance.name] ?? null);

                    return (
                        <div key={instance.name}>
                            <div
                                className="flex items-center gap-3 py-3 px-4 bg-surface border border-border rounded-lg hover:bg-surface-hover hover:border-primary hover:shadow-sm cursor-pointer transition-all duration-200 ease-in-out"
                                onClick={e => {
                                    if (disabled) return;
                                    if (
                                        e.target.tagName === 'LABEL' ||
                                        e.target.tagName === 'INPUT'
                                    )
                                        return;
                                    handleInstanceToggle(instance.name, !isSelected);
                                }}
                                role="button"
                                tabIndex={disabled ? -1 : 0}
                                onKeyDown={e => {
                                    if ((e.key === ' ' || e.key === 'Enter') && !disabled) {
                                        e.preventDefault();
                                        handleInstanceToggle(instance.name, !isSelected);
                                    }
                                }}
                                aria-pressed={isSelected}
                                aria-disabled={disabled}
                            >
                                <CheckboxBase
                                    id={instanceId}
                                    name="plex-scope-instances"
                                    checked={isSelected}
                                    onChange={e =>
                                        handleInstanceToggle(instance.name, e.target.checked)
                                    }
                                    disabled={disabled}
                                />
                                <div className="flex flex-col">
                                    <FieldLabel
                                        htmlFor={instanceId}
                                        label={humanize(instance.name)}
                                        className="text-sm font-normal leading-normal text-fg cursor-pointer select-none"
                                    />
                                    {instance.url && (
                                        <div className="text-xs text-fg-muted">{instance.url}</div>
                                    )}
                                </div>
                            </div>

                            {isSelected && (
                                <div className="flex flex-col gap-4 border-l-2 border-border-subtle pl-4 mt-2 mb-2">
                                    {showAddPosters && (
                                        <ToggleRow
                                            label="Upload posters to this Plex instance"
                                            checked={entry.add_posters}
                                            disabled={disabled}
                                            onChange={v =>
                                                updateEntry(instance.name, { add_posters: v })
                                            }
                                        />
                                    )}

                                    {showMatchCollections && (
                                        <ToggleRow
                                            label="Match collections in selected libraries"
                                            checked={entry.match_collections}
                                            disabled={disabled}
                                            onChange={v =>
                                                updateEntry(instance.name, { match_collections: v })
                                            }
                                        />
                                    )}

                                    <PlexScopeLibrarySelector
                                        instanceName={instance.name}
                                        catalogLibraries={catalogLibs}
                                        selectedLibraries={entry.library_names}
                                        onLibrariesChange={libs =>
                                            updateEntry(instance.name, { library_names: libs })
                                        }
                                        disabled={disabled}
                                        scopeId={scopeId}
                                    />
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        );
    }
);

PlexScopeSelector.displayName = 'PlexScopeSelector';

/**
 * InstancesField component - Schema-driven instances selection
 *
 * @param {Object} props - Component props
 * @param {Object} props.field - Field configuration object from schema
 * @param {Array} props.value - Current field value (mixed array of strings and objects)
 * @param {Function} props.onChange - Value change handler
 * @param {boolean} props.disabled - Field disabled state
 * @param {boolean} props.highlightInvalid - Show validation error state
 * @param {string} props.errorMessage - Error message to display
 */
export const InstancesField = React.memo(
    ({
        field,
        value = [],
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
    }) => {
        // Parse schema configuration with stable reference
        const instanceTypes = useMemo(() => field.instance_types || [], [field.instance_types]);
        const showPosterOption = field.add_posters_option === true;
        const isRequired = field.required === true;
        // When the backend model is `List[str]` (e.g. poster_cleanarr,
        // unmatched_assets), set valueFormat='string' on the schema so we emit
        // plain instance names instead of the full {instance, library_names} dict
        // that would fail pydantic validation.
        const valueFormat = field.valueFormat === 'string' ? 'string' : 'object';

        // Per-mount ID prefix so instance/library checkbox IDs don't collide
        // across multiple `instances` fields rendered on the same page
        // (the Modules page mounts every module's accordion at once).
        const rawId = useId();
        const scopeId = `${rawId.replace(/[^A-Za-z0-9_-]/g, '')}-`;

        // Load instances data using proper CHUB pattern
        const {
            data: instancesResponse,
            isLoading: loading,
            error: loadError,
        } = useApiData({
            apiFunction: instancesAPI.fetchInstances,
            options: {
                immediate: true,
                showErrorToast: false, // Don't show toast errors for field-level API calls
            },
        });

        // Extract instances from API response and transform to expected format
        // instancesAPI.fetchInstances() already unwraps .data from the CHUB response
        const instances = useMemo(() => {
            if (!instancesResponse) {
                return [];
            }

            const instancesData = instancesResponse;
            const transformedInstances = [];

            // Transform nested object structure to flat array
            Object.entries(instancesData).forEach(([serviceType, serviceInstances]) => {
                Object.entries(serviceInstances || {}).forEach(([instanceName, instanceConfig]) => {
                    transformedInstances.push({
                        type: serviceType,
                        name: instanceName,
                        url: instanceConfig.url,
                        api: instanceConfig.api,
                    });
                });
            });

            return transformedInstances;
        }, [instancesResponse]);

        // Parse current value into service-specific selections
        const serviceSelections = useMemo(() => {
            const selections = {};
            const safeValue = Array.isArray(value) ? value : [];

            instanceTypes.forEach(serviceType => {
                if (serviceType === 'plex') {
                    // Plex handles complex objects
                    selections[serviceType] = safeValue.filter(item => {
                        if (!instances || !Array.isArray(instances)) {
                            return false;
                        }
                        if (typeof item === 'string') {
                            return instances.some(
                                inst => inst.type === 'plex' && inst.name === item
                            );
                        }
                        if (typeof item === 'object' && (item.instance || item.name)) {
                            const itemName = item.instance || item.name;
                            return instances.some(
                                inst => inst.type === 'plex' && inst.name === itemName
                            );
                        }
                        if (typeof item === 'object' && !item.instance && !item.name) {
                            // Handle config format: {plex_1: {library_names: [...], add_posters: true}}
                            const plexInstanceNames = Object.keys(item);
                            return plexInstanceNames.some(plexName =>
                                instances.some(
                                    inst => inst.type === 'plex' && inst.name === plexName
                                )
                            );
                        }
                        return false;
                    });
                } else {
                    // Other services use simple strings
                    selections[serviceType] = safeValue.filter(item => {
                        if (!instances || !Array.isArray(instances)) {
                            return false;
                        }
                        if (typeof item === 'string') {
                            // Check if this string matches this service type
                            return instances.some(
                                inst => inst.type === serviceType && inst.name === item
                            );
                        }
                        return false;
                    });
                }
            });

            return selections;
        }, [value, instanceTypes, instances]);

        // Update selection for a specific service type
        const updateServiceSelection = useCallback(
            (serviceType, newSelection) => {
                const otherSelections = instanceTypes
                    .filter(type => type !== serviceType)
                    .flatMap(type => serviceSelections[type] || []);

                // Preserve saved instance-name strings not recognized by any
                // configured service (e.g. an instance renamed/removed in
                // Settings→Instances). Rebuilding purely from recognized
                // selections would silently drop them on an unrelated toggle.
                const recognized = instanceTypes.flatMap(type => serviceSelections[type] || []);
                const safeValue = Array.isArray(value) ? value : [];
                const unrecognized = safeValue.filter(
                    item => typeof item === 'string' && !recognized.includes(item)
                );

                onChange([...otherSelections, ...newSelection, ...unrecognized]);
            },
            [instanceTypes, serviceSelections, onChange, value]
        );

        // Toggle a single ARR instance pill — recompute that service type's
        // string selection and route through updateServiceSelection so the
        // emitted value shape (plain instance-name strings) is unchanged.
        const handleArrToggle = useCallback(
            (serviceType, name, checked) => {
                const current = serviceSelections[serviceType] || [];
                const next = checked ? [...current, name] : current.filter(n => n !== name);
                updateServiceSelection(serviceType, next);
            },
            [serviceSelections, updateServiceSelection]
        );

        const inputId = `field-${field.key}`;

        // Show loading state
        if (loading) {
            return (
                <FieldWrapper invalid={highlightInvalid}>
                    <FieldLabel
                        label={field.label}
                        required={isRequired}
                        helpText={field.helpText}
                    />
                    <div className="flex flex-col items-center justify-center gap-3 text-center bg-surface border-2 text-fg-muted">
                        <div className="w-8 h-8 border-2 border-border border-t-primary rounded-full animate-spin" />
                        <span>Loading instances...</span>
                    </div>
                    {field.description && (
                        <FieldDescription id={`${inputId}-desc`} description={field.description} />
                    )}
                </FieldWrapper>
            );
        }

        // Show error state
        if (loadError) {
            return (
                <FieldWrapper invalid={true}>
                    <FieldLabel
                        label={field.label}
                        required={isRequired}
                        helpText={field.helpText}
                    />
                    <div className="flex flex-col items-center gap-3 text-center bg-surface border-2 border-error">
                        <div>⚠️</div>
                        <div className="flex flex-col gap-2">
                            <div className="font-semibold text-base">Failed to load instances</div>
                            <div className="text-sm">
                                {loadError?.message || 'Unknown error occurred'}
                            </div>
                        </div>
                    </div>
                    {field.description && (
                        <FieldDescription id={`${inputId}-desc`} description={field.description} />
                    )}
                </FieldWrapper>
            );
        }

        // plex_scope type — entirely separate render path, existing behavior untouched
        if (field.type === 'plex_scope') {
            return (
                <FieldWrapper invalid={highlightInvalid}>
                    <FieldLabel
                        label={field.label}
                        required={isRequired}
                        helpText={field.helpText}
                    />
                    <div id={inputId} className="flex flex-col gap-4">
                        <h4 className="text-lg font-bold text-fg mb-2 border-b border-border pb-2">
                            Plex
                        </h4>
                        <PlexScopeSelector
                            instances={instances}
                            value={value}
                            onChange={onChange}
                            showAddPosters={field.add_posters_option === true}
                            showMatchCollections={field.match_collections_option === true}
                            disabled={disabled}
                            scopeId={scopeId}
                        />
                    </div>
                    {field.description && (
                        <FieldDescription id={`${inputId}-desc`} description={field.description} />
                    )}
                    {errorMessage && <FieldError id={`${inputId}-error`} message={errorMessage} />}
                </FieldWrapper>
            );
        }

        // ARR service types render as one pill row; Plex (with its libraries /
        // add-posters config) keeps the richer card selector below.
        const arrTypes = instanceTypes.filter(serviceType => serviceType !== 'plex');
        const hasPlex = instanceTypes.includes('plex');

        return (
            <FieldWrapper invalid={highlightInvalid}>
                <FieldLabel label={field.label} required={isRequired} />

                <div id={inputId} className="flex flex-col gap-5">
                    {arrTypes.length > 0 && (
                        <ArrInstancePills
                            instances={instances}
                            arrTypes={arrTypes}
                            selectedByType={serviceSelections}
                            onToggle={handleArrToggle}
                            disabled={disabled}
                        />
                    )}

                    {hasPlex && (
                        <div className="flex flex-col gap-3">
                            {arrTypes.length > 0 && (
                                <span className="font-mono text-[10px] tracking-[0.8px] text-fg-subtle">
                                    PLEX
                                </span>
                            )}
                            <PlexInstanceSelector
                                instances={instances}
                                selectedInstances={serviceSelections.plex || []}
                                onSelectionChange={newSelection =>
                                    updateServiceSelection('plex', newSelection)
                                }
                                showPosterOption={showPosterOption}
                                disabled={disabled}
                                valueFormat={valueFormat}
                                scopeId={scopeId}
                            />
                        </div>
                    )}
                </div>

                {field.description && (
                    <FieldDescription id={`${inputId}-desc`} description={field.description} />
                )}

                {errorMessage && <FieldError id={`${inputId}-error`} message={errorMessage} />}
            </FieldWrapper>
        );
    }
);

InstancesField.displayName = 'InstancesField';

export default InstancesField;
