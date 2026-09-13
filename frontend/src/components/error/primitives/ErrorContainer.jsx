import React, { useEffect, useId, useRef } from 'react';
import PropTypes from 'prop-types';
import { useFocusTrap } from '../../../hooks/useFocusTrap';

const ErrorDialog = ({ title, description, children, className }) => {
    const dialogRef = useRef(null);
    const titleId = useId();
    const descriptionId = useId();
    useFocusTrap(dialogRef, true);

    // Runs after useFocusTrap's effect, which focuses nothing when there is no focusable child.
    useEffect(() => {
        const dialog = dialogRef.current;
        if (dialog && !dialog.contains(document.activeElement)) dialog.focus();
    }, []);

    return (
        <div className="fixed inset-0 z-modal-backdrop bg-overlay backdrop-blur-sm font-sans flex items-center justify-center p-4">
            <div
                ref={dialogRef}
                role="alertdialog"
                aria-modal="true"
                aria-labelledby={titleId}
                aria-describedby={description ? descriptionId : undefined}
                tabIndex={-1}
                className={`relative bg-surface border-2 border-error rounded-lg p-6 max-w-lg w-full max-h-screen overflow-y-auto shadow-xl z-modal focus:outline-none ${className}`}
            >
                <h2
                    id={titleId}
                    className="text-error text-2xl font-bold m-0 mb-4 text-center leading-tight"
                >
                    {title}
                </h2>
                {description && (
                    <p
                        id={descriptionId}
                        className="text-fg text-base m-0 mb-5 text-center leading-relaxed"
                    >
                        {description}
                    </p>
                )}
                {children}
            </div>
        </div>
    );
};

ErrorDialog.propTypes = {
    title: PropTypes.node.isRequired,
    description: PropTypes.node,
    children: PropTypes.node.isRequired,
    className: PropTypes.string.isRequired,
};

/** Error layout wrapper: modal alert dialog, centred page card, or inline banner. */
export const ErrorContainer = ({ mode = 'page', title, description, children, className = '' }) => {
    if (mode === 'modal') {
        return (
            <ErrorDialog
                // `||` on purpose: an empty-string title would also leave the dialog unnamed.
                title={title || 'Something went wrong'}
                description={description}
                className={className}
            >
                {children}
            </ErrorDialog>
        );
    }

    if (mode === 'page') {
        return (
            <div className="min-h-content p-4 font-sans">
                <div
                    className={`max-w-2xl w-full bg-surface border-2 border-error rounded-lg p-8 shadow-xl mx-auto ${className}`}
                >
                    {children}
                </div>
            </div>
        );
    }

    return (
        <div className={`bg-surface border border-error rounded-md my-2 font-sans ${className}`}>
            <div className="p-4">{children}</div>
        </div>
    );
};

ErrorContainer.propTypes = {
    mode: PropTypes.oneOf(['modal', 'page', 'inline']),
    title: PropTypes.node,
    description: PropTypes.node,
    children: PropTypes.node.isRequired,
    className: PropTypes.string,
};
