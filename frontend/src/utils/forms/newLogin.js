/** Why a new login can't be saved yet, or null. Mirrors /api/auth/setup's checks. */
export const newLoginError = (username, password, confirm) => {
    if (!username.trim() || password.length < 8) {
        return 'Username required and password must be at least 8 characters';
    }
    if (password !== confirm) return 'Passwords do not match';
    return null;
};
