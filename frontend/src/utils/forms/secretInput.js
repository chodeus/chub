/** Props marking an input a secret, not a credential — browsers ignore autocomplete="off". */
export const SECRET_INPUT_PROPS = {
    autoComplete: 'new-password',
    'data-1p-ignore': '',
    'data-lpignore': 'true',
    'data-bwignore': '',
    'data-form-type': 'other',
};
