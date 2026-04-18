import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext.jsx';

const LoginPage = () => {
    const { authConfigured, login, setup } = useAuth();
    const isSetup = authConfigured === false;

    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [errorMsg, setErrorMsg] = useState('');
    const [submitting, setSubmitting] = useState(false);

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
            if (isSetup) {
                await setup(username, password);
            } else {
                await login(username, password);
            }
        } catch (err) {
            setErrorMsg(err.message || 'Authentication failed.');
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="login-page">
            <div className="login-card">
                <div className="login-header">
                    <img src="/img/favicon-64x64.png" alt="CHUB Logo" className="login-logo" />
                    <h1>CHUB</h1>
                    <p>{isSetup ? 'Create your admin account' : 'Sign in to continue'}</p>
                </div>

                <form onSubmit={handleSubmit} className="login-form">
                    {errorMsg && <div className="login-error">{errorMsg}</div>}

                    <div className="login-field">
                        <label htmlFor="username">Username</label>
                        <input
                            id="username"
                            type="text"
                            autoComplete="username"
                            value={username}
                            onChange={e => setUsername(e.target.value)}
                            disabled={submitting}
                        />
                    </div>

                    <div className="login-field">
                        <label htmlFor="password">Password</label>
                        <input
                            id="password"
                            type="password"
                            autoComplete={isSetup ? 'new-password' : 'current-password'}
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                            disabled={submitting}
                        />
                    </div>

                    {isSetup && (
                        <div className="login-field">
                            <label htmlFor="confirmPassword">Confirm Password</label>
                            <input
                                id="confirmPassword"
                                type="password"
                                autoComplete="new-password"
                                value={confirmPassword}
                                onChange={e => setConfirmPassword(e.target.value)}
                                disabled={submitting}
                            />
                        </div>
                    )}

                    <button type="submit" className="login-button" disabled={submitting}>
                        {submitting ? 'Please wait...' : isSetup ? 'Create Account' : 'Sign In'}
                    </button>
                </form>
            </div>

            <style>{`
                .login-page {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    min-height: 100vh;
                    background: var(--bg);
                    padding: 1rem;
                }
                .login-card {
                    width: 100%;
                    max-width: 380px;
                    background: var(--surface);
                    border: 1px solid var(--border-light);
                    border-radius: var(--radius-xl, 24px);
                    padding: 2rem;
                }
                .login-header {
                    text-align: center;
                    margin-bottom: 1.5rem;
                }
                .login-logo {
                    width: 64px;
                    height: 64px;
                    margin-bottom: 0.75rem;
                }
                .login-header h1 {
                    font-family: var(--font-display);
                    font-size: 1.75rem;
                    font-weight: 700;
                    color: var(--text-primary);
                    margin: 0 0 0.25rem;
                }
                .login-header p {
                    color: var(--text-secondary);
                    font-size: 0.875rem;
                    margin: 0;
                }
                .login-form {
                    display: flex;
                    flex-direction: column;
                    gap: 1rem;
                }
                .login-field label {
                    display: block;
                    font-size: 0.8125rem;
                    font-weight: 500;
                    color: var(--text-secondary);
                    margin-bottom: 0.375rem;
                }
                .login-field input {
                    width: 100%;
                    padding: 0.625rem 0.75rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-lg, 16px);
                    background: var(--surface);
                    color: var(--text-primary);
                    font-size: 0.875rem;
                    outline: none;
                    box-sizing: border-box;
                }
                .login-field input:focus {
                    border-color: var(--primary);
                    box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 20%, transparent);
                }
                .login-error {
                    background: color-mix(in srgb, var(--error) 10%, transparent);
                    border: 1px solid color-mix(in srgb, var(--error) 30%, transparent);
                    color: var(--error);
                    padding: 0.625rem 0.75rem;
                    border-radius: var(--radius-lg, 16px);
                    font-size: 0.8125rem;
                }
                .login-button {
                    width: 100%;
                    padding: 0.75rem;
                    border: none;
                    border-radius: var(--radius-lg, 16px);
                    background: var(--primary);
                    color: var(--primary-text, #fff);
                    font-size: 0.875rem;
                    font-weight: 600;
                    cursor: pointer;
                    margin-top: 0.5rem;
                }
                .login-button:hover:not(:disabled) {
                    background: var(--primary-hover);
                }
                .login-button:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                }
            `}</style>
        </div>
    );
};

export default LoginPage;
