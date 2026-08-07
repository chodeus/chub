/**
 * PosterHealReviewPage
 *
 * Review surface for the poster_self_heal module. Lists open proposals (each a
 * current -> proposed filename rename that heals a stale id / title / year) and
 * lets the user apply or dismiss them. Pending items (a title that matches more
 * than one library item) are shown but can't be one-click applied.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { PageHeader } from '../../components/ui/PageHeader';
import { useToast } from '../../contexts/ToastContext';
import { posterSelfHealAPI } from '../../utils/api/posterSelfHeal';

const DRIFT_LABEL = {
    ambiguous: 'Needs a pick',
    backfill: 'Add IDs',
};

const driftLabel = drift => {
    if (!drift) return 'Rename';
    if (DRIFT_LABEL[drift]) return DRIFT_LABEL[drift];
    return drift
        .split('+')
        .map(p => (p === 'backfill' ? 'Add IDs' : p.toUpperCase()))
        .join(' · ');
};

const TYPE_LABEL = {
    poster: 'Poster',
    logo: 'Logo',
    background: 'Background',
    squareart: 'Square Art',
};

const TypePills = ({ types, muted }) =>
    types.length === 0 ? (
        <span className="text-[11px] text-fg-dim italic">nothing routed here</span>
    ) : (
        <span className="flex items-center gap-[5px] flex-wrap">
            {types.map(t => (
                <span
                    key={t}
                    className={`inline-flex items-center h-[22px] px-2 rounded-full text-[11px] font-medium ${
                        muted ? 'bg-surface text-fg-subtle' : 'bg-primary/15 text-primary'
                    }`}
                >
                    {TYPE_LABEL[t] || t}
                </span>
            ))}
        </span>
    );

const CoverageRow = ({ icon, name, value, types, muted }) => (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2 rounded-[9px] bg-surface-inset border border-border-light">
        <span className="material-symbols-outlined text-[17px] text-fg-dim" aria-hidden="true">
            {icon}
        </span>
        <span className="text-[12.5px] font-medium text-fg">{name || 'Unnamed'}</span>
        <span className="font-mono text-[11.5px] text-fg-muted break-all">{value}</span>
        <span className="ml-auto">
            <TypePills types={types} muted={muted} />
        </span>
    </div>
);

/**
 * What the next run will scan. Deliberately shows the HEAL's scope, which is
 * wider than the maker's routing — a location claiming no types saves nothing
 * but is still scanned, so it is listed rather than filtered out.
 */
const CoveragePanel = () => {
    const [cov, setCov] = useState(null);
    const [failed, setFailed] = useState(false);

    useEffect(() => {
        let active = true;
        (async () => {
            try {
                const res = await posterSelfHealAPI.coverage();
                if (active) setCov(res?.data || null);
            } catch {
                if (active) setFailed(true); // non-fatal: the review list still works
            }
        })();
        return () => {
            active = false;
        };
    }, []);

    if (failed || !cov) return null;

    const folders = cov.folders || [];
    const drives = cov.drives || [];
    const unrouted = cov.unrouted_types || [];

    return (
        <section className="flex flex-col gap-2.5 p-4 rounded-xl bg-surface border border-border">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <h2 className="font-display text-[13.5px] font-semibold text-fg m-0">
                    Kept up to date
                </h2>
                <span className="inline-flex items-center h-[22px] px-2.5 rounded-md bg-surface-inset border border-border font-mono text-[11px] text-fg-muted">
                    {folders.length} folders · {drives.length} Drives
                </span>
                <Link
                    to="/settings/modules/cl2k_maker"
                    className="ml-auto text-[12px] font-medium text-accent hover:underline"
                >
                    Edit in Module Settings →
                </Link>
            </div>

            {!cov.available ? (
                <p className="text-[12px] text-fg-subtle m-0">
                    The CL2K Maker extension isn’t available, so nothing is being healed.
                </p>
            ) : folders.length === 0 && drives.length === 0 ? (
                <p className="text-[12px] text-fg-subtle m-0">
                    No save locations are configured — the healer has nothing to scan.
                </p>
            ) : (
                <>
                    <div className="flex flex-col gap-1.5">
                        {folders.map(f => (
                            <CoverageRow
                                key={f.path}
                                icon="folder"
                                name={f.name}
                                value={f.path}
                                types={f.types || []}
                                muted
                            />
                        ))}
                        {drives.map(d => (
                            <CoverageRow
                                key={d.folder_id}
                                icon="cloud"
                                name={d.name}
                                value={d.folder_id}
                                types={d.heals_types || []}
                            />
                        ))}
                    </div>
                    <p className="text-[11.5px] text-fg-subtle m-0">
                        Every location above is scanned. Folder tags show what the maker saves
                        there; Drive tags show which types are renamed in that Drive.
                    </p>
                    {unrouted.length > 0 && (
                        <p className="flex items-start gap-1.5 text-[11.5px] text-warning m-0">
                            <span
                                className="material-symbols-outlined text-[15px] leading-[1.3]"
                                aria-hidden="true"
                            >
                                info
                            </span>
                            <span>
                                No Drive receives {unrouted.map(t => TYPE_LABEL[t] || t).join(', ')}{' '}
                                art — those files are healed locally only, so anyone syncing your
                                Drive keeps the old names.
                            </span>
                        </p>
                    )}
                </>
            )}
        </section>
    );
};

const ReviewRow = ({ review, busy, onApply, onDismiss }) => {
    const pending = review.status === 'pending' || review.drift_type === 'ambiguous';
    return (
        <div className="flex flex-col gap-3 p-4 rounded-xl bg-surface border border-border md:flex-row md:items-center">
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <span
                        className={`font-mono text-[10px] px-1.5 py-0.5 rounded-[5px] ${
                            pending ? 'bg-warning/15 text-warning' : 'bg-primary/15 text-primary'
                        }`}
                    >
                        {driftLabel(review.drift_type)}
                    </span>
                    <span className="text-[11px] text-fg-subtle">{review.reason}</span>
                </div>
                <div className="font-mono text-[12px] text-fg-subtle line-through truncate">
                    {review.current_filename}
                </div>
                {!pending && (
                    <div className="font-mono text-[12.5px] text-fg mt-0.5 truncate">
                        {review.proposed_filename}
                    </div>
                )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
                {!pending && (
                    <button
                        type="button"
                        onClick={() => onApply(review)}
                        disabled={busy}
                        className="inline-flex items-center h-9 px-4 rounded-lg bg-primary text-on-color font-display text-[13px] font-semibold hover:brightness-110 disabled:opacity-50 transition"
                    >
                        Apply
                    </button>
                )}
                <button
                    type="button"
                    onClick={() => onDismiss(review)}
                    disabled={busy}
                    className="inline-flex items-center h-9 px-3.5 rounded-lg bg-surface-inset border border-border text-fg-muted text-[13px] hover:text-fg disabled:opacity-50 transition-colors"
                >
                    Dismiss
                </button>
            </div>
        </div>
    );
};

export const PosterHealReviewPage = () => {
    const toast = useToast();
    const [reviews, setReviews] = useState([]);
    const [loading, setLoading] = useState(true);
    const [busyId, setBusyId] = useState(null);

    useEffect(() => {
        let active = true;
        (async () => {
            try {
                const res = await posterSelfHealAPI.listReviews();
                if (active) setReviews(res?.data?.reviews || []);
            } catch (err) {
                if (active)
                    toast.error(`Failed to load reviews: ${err?.message || 'unknown error'}`);
            } finally {
                if (active) setLoading(false);
            }
        })();
        return () => {
            active = false;
        };
    }, [toast]);

    const handleApply = useCallback(
        async review => {
            if (busyId != null) return; // another apply/dismiss is in flight
            setBusyId(review.id);
            try {
                const res = await posterSelfHealAPI.apply(review.id);
                toast.success(res?.message || 'Applied');
                setReviews(prev => prev.filter(r => r.id !== review.id));
            } catch (err) {
                toast.error(`Apply failed: ${err?.message || 'unknown error'}`);
            } finally {
                setBusyId(null);
            }
        },
        [toast, busyId]
    );

    const handleDismiss = useCallback(
        async review => {
            if (busyId != null) return; // another apply/dismiss is in flight
            setBusyId(review.id);
            try {
                await posterSelfHealAPI.dismiss(review.id);
                setReviews(prev => prev.filter(r => r.id !== review.id));
            } catch (err) {
                toast.error(`Dismiss failed: ${err?.message || 'unknown error'}`);
            } finally {
                setBusyId(null);
            }
        },
        [toast, busyId]
    );

    return (
        <div className="max-w-6xl mx-auto flex flex-col gap-4">
            <PageHeader
                title="Poster Healer — Review"
                description="Proposed id, title, and year fixes for your CL2K posters. Applying renames the file on your Google Drive and the local source copy."
            />

            {/* Left: what the healer looks at. Right: what needs you. */}
            <div className="flex flex-col lg:flex-row gap-4 items-start">
                <aside className="w-full lg:w-[340px] lg:shrink-0">
                    <CoveragePanel />
                </aside>

                <div className="flex-1 min-w-0 flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                        <span className="text-[13px] text-fg-subtle">
                            {loading ? 'Loading…' : `${reviews.length} needing action`}
                        </span>
                        <Link
                            to="/poster/cl2k-maker"
                            className="text-[13px] font-medium text-accent hover:underline"
                        >
                            ← Back to CL2K Maker
                        </Link>
                    </div>

                    {!loading && reviews.length === 0 ? (
                        <div className="text-center py-16 text-fg-subtle rounded-xl border border-dashed border-border">
                            <span className="material-symbols-outlined text-4xl mb-2 block">
                                task_alt
                            </span>
                            <p>Nothing to review — your CL2K posters are up to date.</p>
                            <p className="text-[12px] mt-1">
                                Run the Poster Healer (or wait for its schedule) to check again.
                            </p>
                        </div>
                    ) : (
                        <div className="flex flex-col gap-2.5">
                            {reviews.map(review => (
                                <ReviewRow
                                    key={review.id}
                                    review={review}
                                    busy={busyId === review.id}
                                    onApply={handleApply}
                                    onDismiss={handleDismiss}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default PosterHealReviewPage;
