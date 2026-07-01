import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import { ensureStreamToken, clearStreamToken } from '../utils/api/streamAuth.js';

const TOKEN_STORAGE_KEY = 'chub-auth-token';
const AuthContext = createContext();

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
};

/**
 * Get stored auth token from localStorage.
 */
const getStoredToken = () => {
    try {
        return localStorage.getItem(TOKEN_STORAGE_KEY) || null;
    } catch {
        return null;
    }
};

export const AuthProvider = ({ children }) => {
    const [token, setToken] = useState(getStoredToken);
    const [user, setUser] = useState(null);
    const [authConfigured, setAuthConfigured] = useState(null); // null = loading
    const [setupComplete, setSetupComplete] = useState(null); // null = loading
    const [loading, setLoading] = useState(true);

    /**
     * Check the backend auth status on mount and validate any stored token.
     * All setState calls happen inside promise callbacks so the hooks linter
     * treats them as "external subscription" updates, not synchronous effect-body writes.
     */
    useEffect(() => {
        let cancelled = false;

        const run = () =>
            fetch('/api/auth/status')
                .then(res => res.json())
                .then(async data => {
                    if (cancelled) return;
                    if (!data.success) {
                        setAuthConfigured(false);
                        return;
                    }
                    const configured = data.data.configured;
                    setAuthConfigured(configured);

                    // If auth is configured and we have a stored token, validate it
                    // and restore the username for the app chrome.
                    const storedToken = getStoredToken();
                    if (!configured || !storedToken) return;
                    try {
                        const validateRes = await fetch('/api/auth/me', {
                            headers: { Authorization: `Bearer ${storedToken}` },
                        });
                        if (cancelled) return;
                        if (validateRes.status === 401) {
                            localStorage.removeItem(TOKEN_STORAGE_KEY);
                            setToken(null);
                            setUser(null);
                            return;
                        }
                        if (validateRes.ok) {
                            const me = await validateRes.json();
                            if (!cancelled) {
                                setUser(me?.data?.username || null);
                            }
                        }
                    } catch {
                        // Network error during validation — keep token, let normal
                        // API calls surface the auth error if needed
                    }
                })
                .catch(() => {
                    if (!cancelled) setAuthConfigured(false);
                });

        // First-run gate. Fail-safe to "complete" on any error so a status
        // hiccup never traps an existing user inside the wizard.
        const setupStatus = () =>
            fetch('/api/setup/status')
                .then(res => res.json())
                .then(data => {
                    if (!cancelled) setSetupComplete(data?.data?.completed ?? true);
                })
                .catch(() => {
                    if (!cancelled) setSetupComplete(true);
                });

        Promise.all([run(), setupStatus()]).finally(() => {
            if (!cancelled) setLoading(false);
        });

        return () => {
            cancelled = true;
        };
    }, []);

    const login = useCallback(async (username, password) => {
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.message || 'Login failed');
        }
        const newToken = data.data.token;
        localStorage.setItem(TOKEN_STORAGE_KEY, newToken);
        setToken(newToken);
        setUser(data.data.username);
        return data;
    }, []);

    const setup = useCallback(async (username, password) => {
        const res = await fetch('/api/auth/setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.message || 'Setup failed');
        }
        const newToken = data.data.token;
        localStorage.setItem(TOKEN_STORAGE_KEY, newToken);
        setToken(newToken);
        setUser(data.data.username);
        setAuthConfigured(true);
        return data;
    }, []);

    // Keep a short-lived stream token warm while authenticated so image/SSE URLs
    // never carry the full session token (see utils/api/streamAuth).
    useEffect(() => {
        if (!token) return undefined;
        ensureStreamToken();
        const id = setInterval(ensureStreamToken, 4 * 60 * 1000);
        return () => clearInterval(id);
    }, [token]);

    const logout = useCallback(() => {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        clearStreamToken();
        setToken(null);
        setUser(null);
    }, []);

    /**
     * Persist that the first-run wizard is done so it no longer gates the app.
     * Optimistically flips local state even if the POST fails (the backfill /
     * next status check self-heals) so finishing the wizard never dead-ends.
     */
    const markSetupComplete = useCallback(async () => {
        try {
            const storedToken = getStoredToken();
            await fetch('/api/setup/complete', {
                method: 'POST',
                headers: storedToken ? { Authorization: `Bearer ${storedToken}` } : {},
            });
        } catch {
            // ignore — local state still advances
        }
        setSetupComplete(true);
    }, []);

    const isAuthenticated = Boolean(token);

    const value = {
        token,
        user,
        isAuthenticated,
        authConfigured,
        setupComplete,
        loading,
        login,
        setup,
        logout,
        markSetupComplete,
    };

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

AuthProvider.propTypes = {
    children: PropTypes.node.isRequired,
};
