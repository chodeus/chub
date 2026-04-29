import React, { useCallback, useMemo, useState } from 'react';

import { borderReplacerrAPI } from '../../utils/api/border_replacerr.js';
import { useApiData } from '../../hooks/useApiData.js';
import { LoadingButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

/**
 * Border Replacerr — Live preview gallery.
 *
 * Renders side-by-side "original | bordered" composites for a small mix of
 * the user's matched media (2 movies + 2 series + 2 collections by default).
 * The holiday dropdown lets the user preview any configured holiday's palette
 * — useful for sanity-checking border colors before a real run touches the
 * whole library.
 *
 * The page is intentionally thin — all the bordering math runs server-side
 * in /api/border-replacerr/preview so the preview is always faithful to a
 * real BorderReplacerr run.
 */
const BorderPreviewPage = () => {
    const [holiday, setHoliday] = useState('current');

    // Holiday options for the dropdown.
    const { data: optionsResponse, isLoading: isLoadingOptions } = useApiData({
        apiFunction: borderReplacerrAPI.fetchOptions,
        options: { showErrorToast: false },
    });
    const options = useMemo(() => optionsResponse?.data?.options || [], [optionsResponse]);

    // Preview composites — re-fires whenever `holiday` changes.
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

    const errorMessage = previewError?.message || null;

    const handleHolidayChange = useCallback(e => {
        setHoliday(e.target.value);
    }, []);

    const headerActions = useMemo(
        () => (
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
        ),
        [holiday, options, isLoadingOptions, isGenerating, handleHolidayChange, refreshPreview]
    );

    return (
        <div className="p-4 md:p-6 max-w-6xl mx-auto">
            <PageHeader
                title="Border Replacerr"
                description="Preview the configured border on a small mix of your real posters before committing a full run."
                icon="border_outer"
                actions={headerActions}
            />

            {errorMessage && (
                <div className="mt-4 p-3 bg-error-bg border border-error-border text-error rounded">
                    <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-sm">error</span>
                        {errorMessage}
                    </div>
                </div>
            )}

            <div className="mt-4 text-sm text-secondary flex flex-wrap gap-x-6 gap-y-1">
                {borderWidth != null && (
                    <span>
                        <span className="text-tertiary">Border width: </span>
                        <span className="text-primary font-medium">{borderWidth}px</span>
                    </span>
                )}
                {activeHoliday && (
                    <span>
                        <span className="text-tertiary">Active holiday: </span>
                        <span className="text-primary font-medium">{activeHoliday}</span>
                    </span>
                )}
                {paletteSize === 0 && previewData && (
                    <span className="text-warning">
                        No colors configured — previewing the &quot;remove border&quot; path.
                    </span>
                )}
            </div>

            {isGenerating && previews.length === 0 && (
                <div className="mt-12 flex justify-center">
                    <Spinner size="large" text="Rendering previews…" center />
                </div>
            )}

            {!isGenerating && previewData && previews.length === 0 && (
                <div className="mt-8 p-6 text-center bg-surface border border-dashed rounded-lg text-secondary">
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
                <div className="mt-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {previews.map(preview => (
                        <PreviewCard key={preview.token} preview={preview} />
                    ))}
                </div>
            )}
        </div>
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
                {preview.color && (
                    <div className="flex items-center gap-1 text-xs text-secondary">
                        <span
                            className="inline-block w-4 h-4 rounded border border-border-subtle"
                            style={{ backgroundColor: preview.color }}
                            aria-hidden="true"
                        />
                        <span className="font-mono">{preview.color.toUpperCase()}</span>
                    </div>
                )}
            </div>
        </div>
    );
};

export default BorderPreviewPage;
