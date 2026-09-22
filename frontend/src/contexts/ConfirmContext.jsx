import { createContext, useContext, useCallback, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Modal } from '../components/modals/Modal.jsx';
import { Button } from '../components/ui/button';

const ConfirmContext = createContext(null);

/** Returns `confirm(messageOrOptions) => Promise<boolean>`, the in-app replacement for window.confirm. */
export function useConfirm() {
    const confirm = useContext(ConfirmContext);
    if (!confirm) {
        throw new Error('useConfirm must be used within a ConfirmProvider');
    }
    return confirm;
}

const normalize = input => (typeof input === 'string' ? { message: input } : input || {});

export function ConfirmProvider({ children }) {
    const [request, setRequest] = useState(null);
    // Held in a ref, not state: settling must not depend on a re-render landing first.
    const resolverRef = useRef(null);

    const settle = useCallback(result => {
        const resolve = resolverRef.current;
        resolverRef.current = null;
        setRequest(null);
        resolve?.(result);
    }, []);

    const confirm = useCallback(
        input =>
            new Promise(resolve => {
                // A second confirm() while one is open would strand the first caller
                // awaiting a promise nothing can settle. Decline it, then take over.
                resolverRef.current?.(false);
                resolverRef.current = resolve;
                setRequest(normalize(input));
            }),
        []
    );

    // Unmounting with a dialog open leaves every awaiting caller hung forever.
    useEffect(
        () => () => {
            resolverRef.current?.(false);
            resolverRef.current = null;
        },
        []
    );

    return (
        <ConfirmContext.Provider value={confirm}>
            {children}
            {request && (
                <ConfirmDialog
                    {...request}
                    onConfirm={() => settle(true)}
                    onCancel={() => settle(false)}
                />
            )}
        </ConfirmContext.Provider>
    );
}

ConfirmProvider.propTypes = { children: PropTypes.node };

const ConfirmDialog = ({
    message,
    title = 'Please confirm',
    confirmLabel = 'Confirm',
    cancelLabel = 'Cancel',
    variant = 'primary',
    onConfirm,
    onCancel,
}) => (
    // onClose covers Escape and the backdrop, both of which must decline rather
    // than leave the caller's promise unsettled.
    <Modal isOpen onClose={onCancel} size="small">
        <Modal.Header>{title}</Modal.Header>
        <Modal.Body>{message}</Modal.Body>
        <Modal.Footer align="right">
            <Button variant="ghost" onClick={onCancel}>
                {cancelLabel}
            </Button>
            <Button variant={variant} onClick={onConfirm}>
                {confirmLabel}
            </Button>
        </Modal.Footer>
    </Modal>
);

ConfirmDialog.propTypes = {
    message: PropTypes.node,
    title: PropTypes.string,
    confirmLabel: PropTypes.string,
    cancelLabel: PropTypes.string,
    variant: PropTypes.string,
    onConfirm: PropTypes.func.isRequired,
    onCancel: PropTypes.func.isRequired,
};
