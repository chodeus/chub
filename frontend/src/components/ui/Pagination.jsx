import React from 'react';
import PropTypes from 'prop-types';
import { Button } from './button';

/**
 * Pagination — Previous / Next + jump-to-page select.
 *
 * Renders nothing when totalPages <= 1, so callers don't need to wrap it in
 * a `totalPages > 1 && ...` guard. The jump-to-page <select> generates one
 * <option> per page; native selects scale fine into the low thousands.
 */
const Pagination = ({ currentPage, totalPages, onPageChange, className = '' }) => {
    if (!totalPages || totalPages <= 1) return null;

    const handleSelect = e => {
        const next = Number(e.target.value);
        if (!Number.isNaN(next) && next !== currentPage) {
            onPageChange(next);
        }
    };

    return (
        <div className={`flex flex-wrap items-center justify-center gap-2 ${className}`}>
            <Button
                variant="ghost"
                size="small"
                disabled={currentPage <= 1}
                onClick={() => onPageChange(currentPage - 1)}
            >
                Previous
            </Button>
            <span className="text-sm text-fg-muted">Page</span>
            <div className="relative">
                <select
                    value={currentPage}
                    onChange={handleSelect}
                    aria-label="Jump to page"
                    className="appearance-none bg-input border border-border rounded-md text-sm text-fg pl-2 pr-7 py-1 cursor-pointer hover:border-primary hover:bg-input-hover focus:ring-primary transition-colors"
                >
                    {Array.from({ length: totalPages }, (_, i) => i + 1).map(n => (
                        <option key={n} value={n}>
                            {n}
                        </option>
                    ))}
                </select>
                <span
                    className="material-symbols-outlined absolute top-1/2 right-1 -translate-y-1/2 pointer-events-none text-fg-muted text-base leading-none"
                    aria-hidden="true"
                >
                    keyboard_arrow_down
                </span>
            </div>
            <span className="text-sm text-fg-muted">of {totalPages}</span>
            <Button
                variant="ghost"
                size="small"
                disabled={currentPage >= totalPages}
                onClick={() => onPageChange(currentPage + 1)}
            >
                Next
            </Button>
        </div>
    );
};

Pagination.propTypes = {
    currentPage: PropTypes.number.isRequired,
    totalPages: PropTypes.number.isRequired,
    onPageChange: PropTypes.func.isRequired,
    className: PropTypes.string,
};

export default Pagination;
