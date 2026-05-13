import React, { useState, useEffect } from 'react';
import { Modal } from './Modal';
import { Button } from '../ui/index.js';
import { mediaAPI } from '../../utils/api/media.js';

/**
 * EditMediaModal - Inline metadata editing for media items
 *
 * Renders a modal form with editable fields for media metadata.
 * Calls PUT /api/media/{id}/metadata on save.
 *
 * @param {Object} props
 * @param {boolean} props.isOpen - Whether the modal is visible
 * @param {Function} props.onClose - Close handler
 * @param {Object} props.item - The media item to edit
 * @param {Function} props.onSave - Called with (id, metadata) on save
 * @param {boolean} props.isSaving - Whether save is in progress
 */
const buildFormDataFromItem = item => ({
    title: item?.title || '',
    year: item?.year || '',
    status: item?.status || '',
    rating: item?.rating || '',
    studio: item?.studio || '',
    language: item?.language || '',
    edition: item?.edition || '',
    genre: item?.genre || '',
});

const formatHistoryTimestamp = ts => {
    if (!ts) return '';
    try {
        return new Date(ts).toLocaleString();
    } catch {
        return ts;
    }
};

const EditMediaModal = ({ isOpen, onClose, item, onSave, isSaving = false }) => {
    const [formData, setFormData] = useState(() => buildFormDataFromItem(item));
    // Reset form when the edited item changes. Using the "store info from previous
    // render" pattern (React docs) rather than a setState-in-effect.
    const [prevItemId, setPrevItemId] = useState(item?.id ?? null);
    if ((item?.id ?? null) !== prevItemId) {
        setPrevItemId(item?.id ?? null);
        setFormData(buildFormDataFromItem(item));
    }

    // Audit trail. Fetched lazily on first expand so opening the modal stays
    // a single render — most opens are quick metadata tweaks, not history reviews.
    // Single state object so the effect makes one transition per fetch resolution,
    // avoiding the react-hooks/set-state-in-effect lint when toggling sub-flags.
    const [historyOpen, setHistoryOpen] = useState(false);
    const [historyState, setHistoryState] = useState({
        status: 'idle',
        items: null,
        error: null,
    });

    // Reset history state when the edited item changes — same render-time pattern.
    const [prevHistoryItemId, setPrevHistoryItemId] = useState(item?.id ?? null);
    if ((item?.id ?? null) !== prevHistoryItemId) {
        setPrevHistoryItemId(item?.id ?? null);
        setHistoryOpen(false);
        setHistoryState({ status: 'idle', items: null, error: null });
    }

    useEffect(() => {
        if (!historyOpen || !item?.id || historyState.status !== 'idle') return;
        let cancelled = false;
        mediaAPI
            .fetchMediaHistory(item.id, 100)
            .then(res => {
                if (cancelled) return;
                setHistoryState({
                    status: 'success',
                    items: res?.data?.history || [],
                    error: null,
                });
            })
            .catch(err => {
                if (cancelled) return;
                setHistoryState({
                    status: 'error',
                    items: [],
                    error: err?.message || 'Failed to load history',
                });
            });
        return () => {
            cancelled = true;
        };
    }, [historyOpen, item?.id, historyState.status]);

    const historyLoading = historyOpen && historyState.status === 'idle' && item?.id;
    const historyError = historyState.status === 'error' ? historyState.error : null;
    const history = historyState.items;

    const handleChange = (field, value) => {
        setFormData(prev => ({ ...prev, [field]: value }));
    };

    const handleSubmit = e => {
        e.preventDefault();
        if (onSave && item) {
            onSave(item.id, formData);
        }
    };

    const fields = [
        { key: 'title', label: 'Title', type: 'text' },
        { key: 'year', label: 'Year', type: 'text' },
        {
            key: 'status',
            label: 'Status',
            type: 'select',
            options: ['', 'available', 'missing', 'downloading', 'monitored'],
        },
        { key: 'rating', label: 'Content Rating', type: 'text', placeholder: 'PG, R, TV-MA...' },
        { key: 'studio', label: 'Studio', type: 'text' },
        { key: 'language', label: 'Language', type: 'text', placeholder: 'en, fr, de...' },
        { key: 'edition', label: 'Edition', type: 'text', placeholder: "Director's Cut..." },
        { key: 'genre', label: 'Genres', type: 'text', placeholder: 'Action, Drama...' },
    ];

    return (
        <Modal isOpen={isOpen} onClose={onClose} size="medium">
            <Modal.Header>Edit Media Metadata</Modal.Header>
            <form onSubmit={handleSubmit}>
                <Modal.Body>
                    {/* Audit-trail panel (collapsed by default). Lazy-fetches on
                        first expand so the modal stays cheap to open. */}
                    {item?.id && (
                        <div className="mb-4 rounded-lg border border-border bg-surface-alt">
                            <button
                                type="button"
                                onClick={() => setHistoryOpen(o => !o)}
                                className="w-full flex items-center justify-between px-3 py-2 text-sm text-secondary hover:text-primary"
                            >
                                <span className="flex items-center gap-2">
                                    <span className="material-symbols-outlined text-base">
                                        history
                                    </span>
                                    Edit history
                                </span>
                                <span className="material-symbols-outlined text-base">
                                    {historyOpen ? 'expand_less' : 'expand_more'}
                                </span>
                            </button>
                            {historyOpen && (
                                <div className="border-t border-border px-3 py-2 max-h-56 overflow-y-auto text-xs">
                                    {historyLoading && <p className="text-tertiary">Loading…</p>}
                                    {historyError && !historyLoading && (
                                        <p className="text-error">{historyError}</p>
                                    )}
                                    {!historyLoading &&
                                        !historyError &&
                                        history &&
                                        history.length === 0 && (
                                            <p className="text-tertiary">
                                                No metadata edits recorded for this item.
                                            </p>
                                        )}
                                    {!historyLoading && history && history.length > 0 && (
                                        <ul className="space-y-1.5">
                                            {history.map(row => (
                                                <li
                                                    key={row.id}
                                                    className="flex flex-wrap items-baseline gap-x-2"
                                                >
                                                    <span className="text-tertiary whitespace-nowrap">
                                                        {formatHistoryTimestamp(row.edited_at)}
                                                    </span>
                                                    <span className="text-primary font-medium">
                                                        {row.field}
                                                    </span>
                                                    <span className="text-tertiary">
                                                        {row.old_value ?? '∅'} →{' '}
                                                        <span className="text-primary">
                                                            {row.new_value ?? '∅'}
                                                        </span>
                                                    </span>
                                                    {row.edited_by && (
                                                        <span className="text-tertiary ml-auto">
                                                            by {row.edited_by}
                                                        </span>
                                                    )}
                                                </li>
                                            ))}
                                        </ul>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {fields.map(field => (
                            <div
                                key={field.key}
                                className={field.key === 'title' ? 'sm:col-span-2' : ''}
                            >
                                <label className="block text-xs font-medium text-secondary mb-1">
                                    {field.label}
                                </label>
                                {field.type === 'select' ? (
                                    <select
                                        value={formData[field.key] || ''}
                                        onChange={e => handleChange(field.key, e.target.value)}
                                        className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-primary text-sm focus:border-primary outline-none"
                                    >
                                        {field.options.map(opt => (
                                            <option key={opt} value={opt}>
                                                {opt || '(none)'}
                                            </option>
                                        ))}
                                    </select>
                                ) : (
                                    <input
                                        type="text"
                                        value={formData[field.key] || ''}
                                        onChange={e => handleChange(field.key, e.target.value)}
                                        placeholder={field.placeholder || ''}
                                        className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-primary text-sm focus:border-primary outline-none"
                                    />
                                )}
                            </div>
                        ))}
                    </div>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={onClose} type="button">
                        Cancel
                    </Button>
                    <Button variant="primary" icon="save" type="submit" disabled={isSaving}>
                        {isSaving ? 'Saving...' : 'Save'}
                    </Button>
                </Modal.Footer>
            </form>
        </Modal>
    );
};

export default EditMediaModal;
