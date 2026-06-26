import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext.jsx';
import { useDocumentTitle } from '../hooks/useDocumentTitle.js';
import { systemAPI } from '../utils/api/system.js';

const DOT_GRID = {
    backgroundImage: 'radial-gradient(rgba(135,103,247,.10) 1px, transparent 1px)',
    backgroundSize: '26px 26px',
    maskImage: 'radial-gradient(900px 520px at 50% 36%, #000 0%, transparent 78%)',
    WebkitMaskImage: 'radial-gradient(900px 520px at 50% 36%, #000 0%, transparent 78%)',
};

const LoginPage = () => {
    useDocumentTitle();
    const { authConfigured, login, setup } = useAuth();
    const isSetup = authConfigured === false;

    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [showPw, setShowPw] = useState(false);
    const [errorMsg, setErrorMsg] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [version, setVersion] = useState('');

    // Best-effort version for the connection footer (public endpoint).
    useEffect(() => {
        let alive = true;
        systemAPI
            .getVersion()
            .then(r => alive && setVersion(r?.data?.version || ''))
            .catch(() => {});
        return () => {
            alive = false;
        };
    }, []);

    const handleSubmit = async e => {
        e.preventDefault();
        setErrorMsg('');

        if (!username.trim() || !password) {
            setErrorMsg('Username and password are required.');
            return;
        }
        if (isSetup) {
            if (password.length < 8) {
                setErrorMsg('Password must be at least 8 characters.');
                return;
            }
            if (password !== confirmPassword) {
                setErrorMsg('Passwords do not match.');
                return;
            }
        }

        setSubmitting(true);
        try {
            if (isSetup) await setup(username, password);
            else await login(username, password);
        } catch (err) {
            setErrorMsg(err.message || 'Authentication failed.');
        } finally {
            setSubmitting(false);
        }
    };

    const fieldError = (cond, val) => (cond && !val ? 'border-error' : 'border-border');
    const labelCls = 'font-mono text-[10px] tracking-wider text-fg-subtle';
    const inputCls =
        'h-[42px] px-3 rounded-lg bg-surface-inset border text-fg text-sm outline-none focus:border-primary transition-colors';

    return (
        <div className="relative min-h-screen flex items-center justify-center p-4 bg-canvas overflow-hidden">
            <div className="absolute inset-0" style={DOT_GRID} aria-hidden="true" />

            <div className="relative w-full max-w-[408px] flex flex-col gap-[22px]">
                {/* Brand */}
                <div className="flex flex-col items-center gap-3.5">
                    <img
                        src="/img/chub-logo.png"
                        alt="CHUB"
                        width={52}
                        height={52}
                        className="w-[52px] h-[52px] rounded-[14px]"
                        style={{ boxShadow: '0 6px 26px rgba(255,201,68,.34)' }}
                    />
                    <div className="text-center leading-tight">
                        <div className="font-display text-[26px] font-bold tracking-[0.5px] text-fg">
                            CHUB
                        </div>
                        <div className="text-[13px] font-medium text-fg-subtle mt-0.5">
                            Media Manager
                        </div>
                    </div>
                </div>

                {/* Card */}
                <form
                    onSubmit={handleSubmit}
                    className="bg-surface border border-border rounded-2xl p-[26px] flex flex-col gap-4"
                    style={{ boxShadow: '0 24px 60px -24px rgba(0,0,0,.8)' }}
                    autoComplete="off"
                >
                    <div>
                        <h1 className="font-display text-[19px] font-semibold text-fg">
                            {isSetup ? 'Create your admin account' : 'Sign in'}
                        </h1>
                        <p className="text-[12.5px] text-fg-subtle mt-1">
                            Local account · this CHUB instance
                        </p>
                    </div>

                    {errorMsg && (
                        <div className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg bg-error/[0.09] border border-error/30">
                            <span className="material-symbols-outlined text-error text-[16px] shrink-0">
                                error
                            </span>
                            <span className="text-xs text-[#f5b7c2]">{errorMsg}</span>
                        </div>
                    )}

                    <label className="flex flex-col gap-1.5">
                        <span className={labelCls}>USERNAME</span>
                        <input
                            type="text"
                            autoComplete="username"
                            value={username}
                            onChange={e => {
                                setUsername(e.target.value);
                                setErrorMsg('');
                            }}
                            disabled={submitting}
                            placeholder="admin"
                            className={`${inputCls} ${fieldError(!!errorMsg, username)} placeholder:text-fg-dim`}
                        />
                    </label>

                    <label className="flex flex-col gap-1.5">
                        <span className={labelCls}>PASSWORD</span>
                        <div className="relative flex items-center">
                            <input
                                type={showPw ? 'text' : 'password'}
                                autoComplete={isSetup ? 'new-password' : 'current-password'}
                                value={password}
                                onChange={e => {
                                    setPassword(e.target.value);
                                    setErrorMsg('');
                                }}
                                disabled={submitting}
                                placeholder="••••••••"
                                className={`${inputCls} flex-1 pr-10 ${fieldError(!!errorMsg, password)} placeholder:text-fg-dim`}
                            />
                            <button
                                type="button"
                                onClick={() => setShowPw(s => !s)}
                                className="absolute right-2.5 text-fg-subtle hover:text-fg flex"
                                aria-label={showPw ? 'Hide password' : 'Show password'}
                            >
                                <span className="material-symbols-outlined text-[18px]">
                                    {showPw ? 'visibility_off' : 'visibility'}
                                </span>
                            </button>
                        </div>
                    </label>

                    {isSetup && (
                        <label className="flex flex-col gap-1.5">
                            <span className={labelCls}>CONFIRM PASSWORD</span>
                            <input
                                type={showPw ? 'text' : 'password'}
                                autoComplete="new-password"
                                value={confirmPassword}
                                onChange={e => setConfirmPassword(e.target.value)}
                                disabled={submitting}
                                placeholder="••••••••"
                                className={`${inputCls} ${fieldError(false, confirmPassword)} placeholder:text-fg-dim`}
                            />
                        </label>
                    )}

                    <button
                        type="submit"
                        disabled={submitting}
                        className="h-11 rounded-[10px] bg-primary text-on-color font-display text-sm font-semibold flex items-center justify-center gap-2 hover:brightness-110 disabled:opacity-60 transition"
                        style={{ boxShadow: '0 5px 20px -6px var(--primary)' }}
                    >
                        {submitting
                            ? isSetup
                                ? 'Creating…'
                                : 'Signing in…'
                            : isSetup
                              ? 'Create account'
                              : 'Sign in'}
                    </button>
                </form>

                {/* Connection footer */}
                <div className="flex items-center justify-center gap-2.5 font-mono text-[11px] text-fg-faint">
                    <span
                        className="w-[7px] h-[7px] rounded-full bg-success"
                        style={{ boxShadow: '0 0 0 3px rgba(108,188,102,.16)' }}
                    />
                    <span>{typeof window !== 'undefined' ? window.location.host : ''}</span>
                    {version && (
                        <>
                            <span className="text-[#3a3566]">·</span>
                            <span>{version}</span>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

export default LoginPage;
