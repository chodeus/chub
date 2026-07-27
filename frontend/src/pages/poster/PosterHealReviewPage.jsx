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
        <div className="max-w-4xl mx-auto flex flex-col gap-4">
            <PageHeader
                title="Poster Healer — Review"
                description="Proposed id, title, and year fixes for your CL2K posters. Applying renames the file on your Google Drive and the local source copy."
            />

            <div className="flex items-center justify-between">
                <span className="text-[13px] text-fg-subtle">
                    {loading ? 'Loading…' : `${reviews.length} open`}
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
                    <span className="material-symbols-outlined text-4xl mb-2 block">task_alt</span>
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
    );
};

export default PosterHealReviewPage;
