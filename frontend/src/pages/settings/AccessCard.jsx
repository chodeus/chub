import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { useAuth } from '../../contexts/AuthContext.jsx';
import { useToast } from '../../contexts/ToastContext';
import { Button, LoadingButton } from '../../components/ui';
import { Modal } from '../../components/modals/Modal';
import { InputBase } from '../../components/fields/primitives';
import { newLoginError } from '../../utils/forms/newLogin.js';

const OPEN_WARNING =
    'Anyone who can reach CHUB can use it and change its settings, including your instance API keys.';

const Field = ({ label, ...inputProps }) => (
    <label className="block mb-3">
        <span className="block text-dense font-medium text-fg-muted mb-1.5">{label}</span>
        <InputBase {...inputProps} />
    </label>
);

Field.propTypes = {
    label: PropTypes.string.isRequired,
};

/** Turns CHUB's login off (needs the current password) or back on (a new login). */
const AccessCard = () => {
    const { authConfigured, user, setup, disableAuth } = useAuth();
    const toast = useToast();
    const [dialog, setDialog] = useState(null);
    const [busy, setBusy] = useState(false);
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [confirm, setConfirm] = useState('');

    if (authConfigured == null) return null;

    const close = () => {
        setDialog(null);
        setUsername('');
        setPassword('');
        setConfirm('');
    };

    const run = async (action, done) => {
        setBusy(true);
        try {
            await action();
            toast.success(done);
            close();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setBusy(false);
        }
    };

    const turnOff = () => run(() => disableAuth(password), 'Login turned off');

    const turnOn = () => {
        const invalid = newLoginError(username, password, confirm);
        if (invalid) {
            toast.error(invalid);
            return;
        }
        run(() => setup(username.trim(), password), 'Login turned on');
    };

    return (
        <div className="bg-surface border border-border rounded-xl p-5">
            <h2 className="font-display text-heading font-semibold mb-1 text-fg">Access</h2>
            {authConfigured ? (
                <>
                    <p className="text-dense text-fg-subtle mb-4">
                        CHUB asks for a login{user ? ` — signed in as ${user}` : ''}.
                    </p>
                    <button
                        type="button"
                        onClick={() => setDialog('off')}
                        className="touch-expand h-9 px-3.5 rounded-lg bg-transparent border border-error/35 text-error text-dense font-semibold hover:bg-error/10 transition-colors"
                    >
                        Turn off login
                    </button>
                </>
            ) : (
                <>
                    <p className="text-dense text-fg-subtle mb-4">
                        The login is off. {OPEN_WARNING}
                    </p>
                    <button
                        type="button"
                        onClick={() => setDialog('on')}
                        className="touch-expand inline-flex items-center gap-2 h-9 px-4 rounded-lg bg-surface-inset border border-border text-fg-muted text-dense font-semibold transition-colors hover:border-border-light hover:text-fg"
                    >
                        <span className="material-symbols-outlined text-base">lock</span>
                        Turn on login
                    </button>
                </>
            )}

            <Modal isOpen={dialog === 'off'} onClose={close} size="small">
                <Modal.Header>Turn off the login?</Modal.Header>
                <Modal.Body>
                    <p className="text-fg-muted mb-4">{OPEN_WARNING}</p>
                    <Field
                        label="Current password"
                        type="password"
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        autoComplete="current-password"
                    />
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={close}>
                        Cancel
                    </Button>
                    <LoadingButton
                        loading={busy}
                        loadingText="Turning off..."
                        variant="danger"
                        icon="lock_open"
                        disabled={!password}
                        onClick={turnOff}
                    >
                        Turn off login
                    </LoadingButton>
                </Modal.Footer>
            </Modal>

            <Modal isOpen={dialog === 'on'} onClose={close} size="small">
                <Modal.Header>Turn on the login</Modal.Header>
                <Modal.Body>
                    <Field
                        label="Username"
                        type="text"
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                        autoComplete="username"
                    />
                    <Field
                        label="Password"
                        type="password"
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        autoComplete="new-password"
                    />
                    <Field
                        label="Confirm password"
                        type="password"
                        value={confirm}
                        onChange={e => setConfirm(e.target.value)}
                        autoComplete="new-password"
                    />
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={close}>
                        Cancel
                    </Button>
                    <LoadingButton
                        loading={busy}
                        loadingText="Turning on..."
                        icon="lock"
                        onClick={turnOn}
                    >
                        Turn on login
                    </LoadingButton>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default AccessCard;
