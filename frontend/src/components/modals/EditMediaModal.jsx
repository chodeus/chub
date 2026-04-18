import React, { useState, useEffect } from 'react';
import { Modal } from './Modal';
import { Button } from '../ui/index.js';

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
const EditMediaModal = ({ isOpen, onClose, item, onSave, isSaving = false }) => {
    const [formData, setFormData] = useState({});

    useEffect(() => {
        if (item) {
            setFormData({
                title: item.title || '',
                year: item.year || '',
                status: item.status || '',
                rating: item.rating || '',
                studio: item.studio || '',
                language: item.language || '',
                edition: item.edition || '',
                genre: item.genre || '',
            });
        }
    }, [item]);

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
