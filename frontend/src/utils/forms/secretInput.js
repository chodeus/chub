/**
 * Props that mark an input as a secret (API key, token), not a login credential.
 * Browsers ignore autocomplete="off" on type=password, so without this a password
 * manager offers the saved site login; the data-* attrs are the vendor opt-outs.
 */
export const SECRET_INPUT_PROPS = {
    autoComplete: 'new-password',
    'data-1p-ignore': '',
    'data-lpignore': 'true',
    'data-bwignore': '',
    'data-form-type': 'other',
};
