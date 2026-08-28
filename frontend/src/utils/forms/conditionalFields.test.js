import { describe, expect, it } from 'vitest';

import { shouldShowField } from './conditionalFields';

// `all_empty` exists so a notice can depend on more than one field — the
// single-`field` conditional form can't express "neither auth method is set".
describe('all_empty condition', () => {
    const notice = {
        key: 'shared_client_id_notice',
        conditional: {
            field: 'gdrive_sa_location',
            condition: 'all_empty',
            value: ['gdrive_sa_location', 'client_id'],
        },
    };

    it('shows when every named field is empty', () => {
        expect(shouldShowField(notice, { gdrive_sa_location: '', client_id: '' })).toBe(true);
    });

    it('shows when the named fields are absent entirely', () => {
        expect(shouldShowField(notice, {})).toBe(true);
    });

    it('hides as soon as one named field is set', () => {
        expect(
            shouldShowField(notice, { gdrive_sa_location: '/config/sa.json', client_id: '' })
        ).toBe(false);
        expect(shouldShowField(notice, { gdrive_sa_location: '', client_id: 'abc' })).toBe(false);
    });

    it('hides when both are set', () => {
        expect(shouldShowField(notice, { gdrive_sa_location: '/sa.json', client_id: 'abc' })).toBe(
            false
        );
    });

    it('does not show for an empty or missing field list', () => {
        const bad = { conditional: { field: 'x', condition: 'all_empty', value: [] } };
        expect(shouldShowField(bad, {})).toBe(false);
    });
});

// The 4th `formData` argument was added for all_empty; the existing 3-arg
// evaluators must be unaffected by it.
describe('existing conditions still evaluate', () => {
    it('is_empty reads the single dependent field', () => {
        const field = { conditional: { field: 'gdrive_sa_location', condition: 'is_empty' } };
        expect(shouldShowField(field, { gdrive_sa_location: '' })).toBe(true);
        expect(shouldShowField(field, { gdrive_sa_location: '/sa.json' })).toBe(false);
    });

    it('equals compares against the schema value', () => {
        const field = { conditional: { field: 'mode', condition: 'equals', value: 'kometa' } };
        expect(shouldShowField(field, { mode: 'kometa' })).toBe(true);
        expect(shouldShowField(field, { mode: 'plex' })).toBe(false);
    });

    it('shows a field with no conditional at all', () => {
        expect(shouldShowField({ key: 'plain' }, {})).toBe(true);
    });
});
