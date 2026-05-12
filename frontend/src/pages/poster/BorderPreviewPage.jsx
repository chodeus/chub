import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { borderReplacerrAPI } from '../../utils/api/border_replacerr.js';
import { configAPI } from '../../utils/api/config.js';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { useUnsavedChangesWarning } from '../../hooks/useUnsavedChangesWarning';
import { Button, LoadingButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';
import { ColorListField } from '../../components/fields/color/ColorListField.jsx';

/**
 * Border Replacerr page.
 *
 * Two responsibilities:
 *   1. Visual editor for border_colors + per-holiday colors and themed
 *      border art. The Module Settings page intentionally only carries
 *      the non-visual knobs (width, schedules, filters) so the basic
 *      "just strip the 26px TPDB border" flow stays uncluttered.
 *   2. Live preview gallery — side-by-side "original | bordered"
 *      composites for a small mix of the user's matched media, rendered
 *      server-side so the preview is always faithful to a real run.
 *
 * Holidays themselves (which holidays exist + their date windows) are
 * still added/removed in Module Settings → Border Replacerr. This page
 * shows the visual side of each one in read-only-metadata form with a
 * link back to Settings for edits to name/schedule.
 */
const BorderReplacerrPage = () => {
    const toast = useToast();

    // ─── Config form state ────────────────────────────────────────────
    const [config, setConfig] = useState(null);
    const [baseline, setBaseline] = useState('');
    const [isLoadingConfig, setIsLoadingConfig] = useState(true);
    const [loadError, setLoadError] = useState(null);
    const [isSaving, setIsSaving] = useState(false);

    // Fetch the whole config once on mount. We need it whole because the
    // save endpoint takes the full document; we splice border_replacerr
    // back in on save.
    const [fullConfig, setFullConfig] = useState(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const resp = await configAPI.fetchConfig({ useCache: false });
                if (cancelled) return;
                const fullCfg = resp?.data || {};
                const br = fullCfg.border_replacerr || {};
                setFullConfig(fullCfg);
                setConfig({
                    border_colors: Array.isArray(br.border_colors) ? br.border_colors : [],
                    holidays: Array.isArray(br.holidays) ? br.holidays : [],
                });
                setBaseline(
                    JSON.stringify({
                        border_colors: Array.isArray(br.border_colors) ? br.border_colors : [],
                        holidays: Array.isArray(br.holidays) ? br.holidays : [],
                    })
                );
            } catch (err) {
                if (!cancelled) setLoadError(err.message || 'Failed to load configuration');
            } finally {
                if (!cancelled) setIsLoadingConfig(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    const isDirty = useMemo(
        () => (config ? JSON.stringify(config) !== baseline : false),
        [config, baseline]
    );
    useUnsavedChangesWarning(isDirty);

    const updateBorderColors = useCallback(colors => {
        setConfig(prev => (prev ? { ...prev, border_colors: colors } : prev));
    }, []);

    const updateHoliday = useCallback((index, patch) => {
        setConfig(prev => {
            if (!prev) return prev;
            const holidays = prev.holidays.map((h, i) => (i === index ? { ...h, ...patch } : h));
            return { ...prev, holidays };
        });
    }, []);

    const handleDiscard = useCallback(() => {
        if (!isDirty) return;
        if (!window.confirm('Discard unsaved changes?')) return;
        try {
            const parsed = JSON.parse(baseline);
            setConfig(parsed);
        } catch {
            // Baseline should always be valid JSON we wrote; defensive only.
        }
    }, [baseline, isDirty]);

    const handleSave = useCallback(async () => {
        if (!config || !fullConfig || !isDirty || isSaving) return;
        try {
            setIsSaving(true);
            const next = {
                ...fullConfig,
                border_replacerr: {
                    ...(fullConfig.border_replacerr || {}),
                    border_colors: config.border_colors,
                    holidays: config.holidays,
                },
            };
            await configAPI.updateConfig(next);
            setFullConfig(next);
            setBaseline(JSON.stringify(config));
            toast.success('Border Replacerr settings saved');
        } catch (err) {
            toast.error(err.message || 'Failed to save');
        } finally {
            setIsSaving(false);
        }
    }, [config, fullConfig, isDirty, isSaving, toast]);

    // Cmd/Ctrl+S → save.
    useEffect(() => {
        const onKey = e => {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's' && isDirty && !isSaving) {
                e.preventDefault();
                handleSave();
            }
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [handleSave, isDirty, isSaving]);

    const headerActions = useMemo(() => {
        const dirtyBadge = isDirty ? (
            <span
                className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-warning-bg text-warning"
                aria-live="polite"
            >
                <span className="material-symbols-outlined text-xs">edit</span>
                Unsaved changes
            </span>
        ) : null;

        return (
            <div className="flex items-center gap-2 flex-wrap">
                {dirtyBadge}
                <Button
                    onClick={handleDiscard}
                    disabled={!isDirty || isSaving}
                    variant="secondary"
                    icon="undo"
                >
                    Discard
                </Button>
                <LoadingButton
                    onClick={handleSave}
                    loading={isSaving}
                    disabled={!isDirty}
                    icon="save"
                >
                    Save changes
                </LoadingButton>
            </div>
        );
    }, [handleDiscard, handleSave, isDirty, isSaving]);

    if (isLoadingConfig) {
        return (
            <div className="p-4 md:p-6">
                <Spinner size="large" text="Loading Border Replacerr…" center />
            </div>
        );
    }

    if (loadError) {
        return (
            <div className="p-4 md:p-6 max-w-6xl mx-auto">
                <div className="p-3 bg-error-bg border border-error-border text-error rounded">
                    {loadError}
                </div>
            </div>
        );
    }

    return (
        <div className="p-4 md:p-6 max-w-6xl mx-auto pb-24">
            <PageHeader
                title="Border Replacerr"
                description="Choose colors and themed border art for default and per-holiday styling, and preview the result on a sample of your real posters."
                icon="border_outer"
                actions={headerActions}
            />

            <DefaultColorsSection
                value={config.border_colors}
                onChange={updateBorderColors}
                disabled={isSaving}
            />

            <HolidaysSection
                holidays={config.holidays}
                onChange={updateHoliday}
                disabled={isSaving}
            />

            <PreviewSection isDirty={isDirty} />
        </div>
    );
};

// ─── Sections ──────────────────────────────────────────────────────────

const SectionHeader = ({ title, description, action = null }) => (
    <div className="flex items-start justify-between gap-3 mb-3">
        <div>
            <h2 className="text-lg font-semibold text-primary">{title}</h2>
            {description && <p className="text-sm text-tertiary mt-1 max-w-2xl">{description}</p>}
        </div>
        {action}
    </div>
);

const DEFAULT_COLOR_FIELD = {
    key: 'border_colors',
    label: 'Default border colors',
    description:
        'Used when no holiday is active. Leave empty to just strip the existing border (poster keeps cropped artwork). Multiple colors cycle per poster.',
    output_format: 'array',
    add_button_text: 'Add color',
};

const DefaultColorsSection = ({ value, onChange, disabled }) => (
    <section className="mt-6 p-4 bg-surface border border-border rounded-lg">
        <SectionHeader
            title="Default border colors"
            description="Active outside any configured holiday window."
        />
        <ColorListField
            field={DEFAULT_COLOR_FIELD}
            value={value}
            onChange={onChange}
            disabled={disabled}
        />
    </section>
);

const HolidaysSection = ({ holidays, onChange, disabled }) => {
    if (!holidays.length) {
        return (
            <section className="mt-6 p-6 bg-surface border border-dashed rounded-lg text-center">
                <span className="material-symbols-outlined text-3xl text-tertiary block mb-2">
                    event
                </span>
                <h2 className="text-lg font-semibold text-primary">No holidays configured</h2>
                <p className="text-sm text-tertiary mt-1">
                    Add holidays (name and date window) in{' '}
                    <Link
                        to="/settings/modules"
                        className="text-primary underline hover:no-underline"
                    >
                        Module Settings → Border Replacerr
                    </Link>
                    . They&apos;ll show up here so you can pick colors and themed border art.
                </p>
            </section>
        );
    }

    return (
        <section className="mt-6">
            <SectionHeader
                title="Holidays"
                description="Per-holiday colors and themed border art. Holiday names and date windows are edited in Module Settings."
            />
            <div className="flex flex-col gap-4">
                {holidays.map((holiday, index) => (
                    <HolidayCard
                        key={`${holiday.name || 'unnamed'}-${index}`}
                        holiday={holiday}
                        onChange={patch => onChange(index, patch)}
                        disabled={disabled}
                    />
                ))}
            </div>
        </section>
    );
};

const HolidayCard = ({ holiday, onChange, disabled }) => {
    const [expanded, setExpanded] = useState(true);
    const colors = Array.isArray(holiday.colors) ? holiday.colors : [];
    const borders = Array.isArray(holiday.borders) ? holiday.borders : [];

    const colorField = useMemo(
        () => ({
            key: `holiday-${holiday.name}-colors`,
            label: 'Colors',
            description:
                'Used when no themed borders are selected below. Multiple colors cycle per poster.',
            output_format: 'array',
            add_button_text: 'Add color',
        }),
        [holiday.name]
    );

    const updateColors = useCallback(next => onChange({ colors: next }), [onChange]);
    const updateBorders = useCallback(next => onChange({ borders: next }), [onChange]);

    return (
        <article className="bg-surface border border-border rounded-lg overflow-hidden">
            <header
                className="flex items-center justify-between p-3 cursor-pointer hover:bg-surface-hover"
                onClick={() => setExpanded(v => !v)}
                role="button"
                tabIndex={0}
                onKeyDown={e => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setExpanded(v => !v);
                    }
                }}
                aria-expanded={expanded}
            >
                <div className="min-w-0 flex-1">
                    <div className="text-base font-medium text-primary truncate">
                        {holiday.name || '(unnamed holiday)'}
                    </div>
                    <div className="text-xs text-tertiary mt-0.5 flex flex-wrap gap-x-3 gap-y-1">
                        <span>{holiday.schedule || 'No schedule set'}</span>
                        <span>·</span>
                        <span>
                            {borders.length > 0
                                ? `${borders.length} themed border${borders.length === 1 ? '' : 's'} (image mode)`
                                : colors.length > 0
                                  ? `${colors.length} color${colors.length === 1 ? '' : 's'}`
                                  : 'No styling yet'}
                        </span>
                    </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <ColorSwatchRow colors={colors} />
                    <span className="material-symbols-outlined text-tertiary" aria-hidden="true">
                        {expanded ? 'expand_less' : 'expand_more'}
                    </span>
                </div>
            </header>

            {expanded && (
                <div className="p-4 border-t border-border-subtle flex flex-col gap-5">
                    <div className="text-xs text-tertiary">
                        Name and date window edited in{' '}
                        <Link
                            to="/settings/modules"
                            className="text-primary underline hover:no-underline"
                        >
                            Module Settings →
                        </Link>
                    </div>

                    <ColorListField
                        field={colorField}
                        value={colors}
                        onChange={updateColors}
                        disabled={disabled}
                    />

                    <BordersPicker
                        holidayName={holiday.name}
                        selected={borders}
                        onChange={updateBorders}
                        disabled={disabled}
                    />

                    {borders.length > 0 && (
                        <div className="text-xs text-tertiary flex items-start gap-2 p-2 rounded bg-info-bg/30">
                            <span className="material-symbols-outlined text-sm shrink-0">info</span>
                            <span>
                                Image mode active — selected border art is composited over each
                                poster and the colors above are not used until you remove all themed
                                borders.
                            </span>
                        </div>
                    )}
                </div>
            )}
        </article>
    );
};

const ColorSwatchRow = ({ colors }) => {
    if (!colors?.length) return null;
    const shown = colors.slice(0, 4);
    const remainder = colors.length - shown.length;
    return (
        <div className="flex items-center gap-1">
            {shown.map((c, i) => (
                <span
                    key={`${c}-${i}`}
                    className="inline-block w-4 h-4 rounded-full border border-border-subtle"
                    style={{ backgroundColor: c }}
                    title={c}
                    aria-hidden="true"
                />
            ))}
            {remainder > 0 && <span className="text-xs text-tertiary">+{remainder}</span>}
        </div>
    );
};

// ─── Borders picker ────────────────────────────────────────────────────

const BordersPicker = ({ holidayName, selected, onChange, disabled }) => {
    const fetchBorders = useCallback(() => {
        if (!holidayName) return Promise.resolve({ data: null });
        return borderReplacerrAPI.fetchBorders(holidayName);
    }, [holidayName]);

    const {
        data: bordersResponse,
        isLoading,
        error,
    } = useApiData({
        apiFunction: fetchBorders,
        options: { showErrorToast: false },
        dependencies: [holidayName],
    });

    const data = bordersResponse?.data || null;

    const toggle = useCallback(
        name => {
            const set = new Set(selected || []);
            if (set.has(name)) set.delete(name);
            else set.add(name);
            // Preserve insertion order (new ones append) — variants cycle in
            // that order at render time.
            const next = [];
            for (const existing of selected || []) {
                if (set.has(existing)) next.push(existing);
            }
            for (const candidate of set) {
                if (!next.includes(candidate)) next.push(candidate);
            }
            onChange(next);
        },
        [selected, onChange]
    );

    return (
        <div>
            <div className="flex items-baseline justify-between mb-2">
                <h3 className="text-sm font-medium text-primary">Themed border art</h3>
                <span className="text-xs text-tertiary">
                    Click thumbnails to add/remove. Order = rotation order per poster.
                </span>
            </div>

            {isLoading && <div className="text-xs text-tertiary">Loading variants…</div>}
            {error && (
                <div className="text-xs text-error">
                    {error.message || 'Failed to load border variants'}
                </div>
            )}

            {data && !data.folder && !isLoading && (
                <div className="text-xs text-tertiary p-3 rounded bg-surface-subtle border border-dashed">
                    No bundled border folder maps to this holiday name. Drop custom PNGs at
                    <code className="mx-1 text-primary">/config/borders/&lt;folder&gt;/</code>
                    to add your own.
                </div>
            )}

            {data?.folder && (
                <>
                    <ThumbnailGroup
                        label="Bundled"
                        holiday={holidayName}
                        source="bundled"
                        variants={data.bundled || []}
                        selected={selected}
                        onToggle={toggle}
                        disabled={disabled}
                        emptyMessage="No bundled variants for this holiday."
                    />
                    <ThumbnailGroup
                        label="Custom"
                        holiday={holidayName}
                        source="user"
                        variants={data.user || []}
                        selected={selected}
                        onToggle={toggle}
                        disabled={disabled}
                        emptyMessage={
                            <>
                                Drop PNG files at{' '}
                                <code className="text-primary">/config/borders/{data.folder}/</code>{' '}
                                to add custom variants.
                            </>
                        }
                    />
                </>
            )}
        </div>
    );
};

const ThumbnailGroup = ({
    label,
    holiday,
    source,
    variants,
    selected,
    onToggle,
    disabled,
    emptyMessage,
}) => (
    <div className="mt-3">
        <div className="text-xs text-secondary uppercase tracking-wide mb-2">{label}</div>
        {variants.length === 0 ? (
            <div className="text-xs text-tertiary p-2">{emptyMessage}</div>
        ) : (
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-2">
                {variants.map(name => {
                    const isSelected = (selected || []).includes(name);
                    return (
                        <button
                            key={`${source}-${name}`}
                            type="button"
                            onClick={() => onToggle(name)}
                            disabled={disabled}
                            aria-pressed={isSelected}
                            className={`relative aspect-[2/3] rounded-md overflow-hidden border-2 transition-all focus:outline-2 focus:outline-primary focus:outline-offset-1 disabled:opacity-50 ${
                                isSelected
                                    ? 'border-primary ring-2 ring-primary/40'
                                    : 'border-border hover:border-border-strong'
                            }`}
                            title={`${name}${isSelected ? ' — selected' : ''}`}
                        >
                            <img
                                src={borderReplacerrAPI.thumbnailUrl(holiday, source, name)}
                                alt={`${label} border variant ${name}`}
                                loading="lazy"
                                className="absolute inset-0 w-full h-full object-cover bg-black"
                            />
                            {isSelected && (
                                <span className="absolute top-1 right-1 inline-flex items-center justify-center w-6 h-6 rounded-full bg-primary text-white shadow">
                                    <span className="material-symbols-outlined text-base">
                                        check
                                    </span>
                                </span>
                            )}
                            <span className="absolute bottom-0 left-0 right-0 text-[11px] font-mono text-white bg-black/60 px-1 py-0.5 truncate">
                                {name}
                            </span>
                        </button>
                    );
                })}
            </div>
        )}
    </div>
);

// ─── Preview section ───────────────────────────────────────────────────

const PreviewSection = ({ isDirty }) => {
    const [holiday, setHoliday] = useState('current');

    const { data: optionsResponse, isLoading: isLoadingOptions } = useApiData({
        apiFunction: borderReplacerrAPI.fetchOptions,
        options: { showErrorToast: false },
    });
    const options = useMemo(() => optionsResponse?.data?.options || [], [optionsResponse]);

    const fetchPreview = useCallback(
        () => borderReplacerrAPI.generatePreview({ count: 6, holiday }),
        [holiday]
    );
    const {
        data: previewResponse,
        isLoading: isGenerating,
        error: previewError,
        refresh: refreshPreview,
    } = useApiData({
        apiFunction: fetchPreview,
        options: { showErrorToast: true },
        dependencies: [holiday],
    });

    const previewData = previewResponse?.data || null;
    const previews = previewData?.previews || [];
    const activeHoliday = previewData?.active_holiday;
    const borderWidth = previewData?.border_width;
    const paletteSize = previewData?.palette_size ?? 0;
    const borderCount = previewData?.border_count ?? 0;
    const mode = previewData?.mode || 'remove';

    const errorMessage = previewError?.message || null;

    const handleHolidayChange = useCallback(e => {
        setHoliday(e.target.value);
    }, []);

    return (
        <section className="mt-8">
            <SectionHeader
                title="Preview"
                description="Side-by-side composites for a small mix of your matched media. The preview reads saved configuration."
                action={
                    <div className="flex items-center gap-3 flex-wrap">
                        <label className="flex items-center gap-2 text-sm text-secondary">
                            <span className="material-symbols-outlined text-base">event</span>
                            <span>Holiday</span>
                            <select
                                value={holiday}
                                onChange={handleHolidayChange}
                                disabled={isLoadingOptions || isGenerating}
                                className="bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
                            >
                                {options.map(opt => (
                                    <option key={opt.value} value={opt.value}>
                                        {opt.label}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <LoadingButton
                            onClick={refreshPreview}
                            loading={isGenerating}
                            disabled={isLoadingOptions}
                            icon="refresh"
                        >
                            Refresh
                        </LoadingButton>
                    </div>
                }
            />

            {isDirty && (
                <div className="mb-3 p-2 rounded text-xs text-warning bg-warning-bg/30 border border-warning-border/40 flex items-start gap-2">
                    <span className="material-symbols-outlined text-sm shrink-0">info</span>
                    <span>
                        Unsaved changes won&apos;t appear in the preview until you save. The preview
                        always reflects the saved configuration.
                    </span>
                </div>
            )}

            {errorMessage && (
                <div className="mb-3 p-3 bg-error-bg border border-error-border text-error rounded">
                    <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-sm">error</span>
                        {errorMessage}
                    </div>
                </div>
            )}

            <div className="mb-3 text-sm text-secondary flex flex-wrap gap-x-6 gap-y-1">
                {mode === 'image' ? (
                    <span>
                        <span className="text-tertiary">Mode: </span>
                        <span className="text-primary font-medium">
                            Image ({borderCount} variant{borderCount === 1 ? '' : 's'})
                        </span>
                    </span>
                ) : (
                    borderWidth != null && (
                        <span>
                            <span className="text-tertiary">Border width: </span>
                            <span className="text-primary font-medium">{borderWidth}px</span>
                        </span>
                    )
                )}
                {activeHoliday && (
                    <span>
                        <span className="text-tertiary">Active holiday: </span>
                        <span className="text-primary font-medium">{activeHoliday}</span>
                    </span>
                )}
                {mode === 'remove' && previewData && (
                    <span className="text-warning">
                        No borders or colors configured — previewing the &quot;remove border&quot;
                        path.
                    </span>
                )}
                {mode === 'color' && paletteSize > 0 && (
                    <span>
                        <span className="text-tertiary">Palette: </span>
                        <span className="text-primary font-medium">
                            {paletteSize} color{paletteSize === 1 ? '' : 's'}
                        </span>
                    </span>
                )}
            </div>

            {isGenerating && previews.length === 0 && (
                <div className="mt-12 flex justify-center">
                    <Spinner size="large" text="Rendering previews…" center />
                </div>
            )}

            {!isGenerating && previewData && previews.length === 0 && (
                <div className="mt-4 p-6 text-center bg-surface border border-dashed rounded-lg text-secondary">
                    <span className="material-symbols-outlined text-4xl text-tertiary block mb-2">
                        image_not_supported
                    </span>
                    <p className="text-primary font-medium">No matched posters yet</p>
                    <p className="text-sm text-tertiary mt-1">
                        Run Poster Renamerr first to populate the matched-media cache, then come
                        back to preview borders.
                    </p>
                </div>
            )}

            {previews.length > 0 && (
                <div className="mt-2 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {previews.map(preview => (
                        <PreviewCard key={preview.token} preview={preview} />
                    ))}
                </div>
            )}
        </section>
    );
};

const PreviewCard = ({ preview }) => {
    const kindLabel =
        preview.kind === 'movie'
            ? 'Movie'
            : preview.kind === 'series'
              ? preview.season_number != null
                  ? `Series · S${String(preview.season_number).padStart(2, '0')}`
                  : 'Series'
              : preview.kind === 'collection'
                ? 'Collection'
                : preview.kind || 'Media';

    return (
        <div className="bg-surface border border-border rounded-lg overflow-hidden flex flex-col">
            <img
                src={borderReplacerrAPI.fileUrl(preview.token)}
                alt={`${preview.title} preview (original on left, bordered on right)`}
                className="w-full h-auto bg-black"
                loading="lazy"
            />
            <div className="p-3 flex items-center justify-between gap-2">
                <div className="min-w-0">
                    <div
                        className="text-sm font-medium text-primary truncate"
                        title={preview.title}
                    >
                        {preview.title}
                    </div>
                    <div className="text-xs text-tertiary">{kindLabel}</div>
                </div>
                {preview.border ? (
                    <div
                        className="text-xs text-secondary font-mono truncate max-w-[120px]"
                        title={preview.border}
                    >
                        {preview.border}
                    </div>
                ) : (
                    preview.color && (
                        <div className="flex items-center gap-1 text-xs text-secondary">
                            <span
                                className="inline-block w-4 h-4 rounded border border-border-subtle"
                                style={{ backgroundColor: preview.color }}
                                aria-hidden="true"
                            />
                            <span className="font-mono">{preview.color.toUpperCase()}</span>
                        </div>
                    )
                )}
            </div>
        </div>
    );
};

export default BorderReplacerrPage;
