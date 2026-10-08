import { newLoginError } from './newLogin.js';

describe('newLoginError', () => {
    it('accepts a username and a matching password of 8+ characters', () => {
        expect(newLoginError('dean', '12345678', '12345678')).toBeNull();
    });

    it.each([
        ['a blank username', '   ', '12345678', '12345678'],
        ['a short password', 'dean', '1234567', '1234567'],
    ])('rejects %s', (_case, username, password, confirm) => {
        expect(newLoginError(username, password, confirm)).toMatch(/at least 8 characters/);
    });

    it('rejects a confirmation that differs', () => {
        expect(newLoginError('dean', '12345678', '12345679')).toBe('Passwords do not match');
    });
});
