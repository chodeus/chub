import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';

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
                    // by hitting a protected endpoint. If the token is stale/invalid
                    // (e.g. after container restart with new JWT secret), clear it.
                    const storedToken = getStoredToken();
                    if (!configured || !storedToken) return;
                    try {
                        const validateRes = await fetch('/api/config', {
                            headers: { Authorization: `Bearer ${storedToken}` },
                        });
                        if (cancelled) return;
                        if (validateRes.status === 401) {
                            localStorage.removeItem(TOKEN_STORAGE_KEY);
                            setToken(null);
                            setUser(null);
                        }
                    } catch {
                        // Network error during validation — keep token, let normal
                        // API calls surface the auth error if needed
                    }
                })
                .catch(() => {
                    if (!cancelled) setAuthConfigured(false);
                })
                .finally(() => {
                    if (!cancelled) setLoading(false);
                });

        run();

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

    const logout = useCallback(() => {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        setToken(null);
        setUser(null);
    }, []);

    const isAuthenticated = Boolean(token);

    const value = {
        token,
        user,
        isAuthenticated,
        authConfigured,
        loading,
        login,
        setup,
        logout,
    };

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

AuthProvider.propTypes = {
    children: PropTypes.node.isRequired,
};
