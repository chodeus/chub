import { describe, expect, it } from 'vitest';

import { shouldShowField } from './conditionalFields';

// `api_flag` exists because only the server can stat the service-account
// keyfile — a path that is set but missing still means the shared client.
describe('api_flag condition', () => {
    const notice = {
        key: 'shared_client_id_notice',
        conditional: {
            field: 'gdrive_sa_location',
            condition: 'api_flag',
            api_lookup: 'gdrive_credentials',
            value: 'shared_client_id',
        },
    };

    const show = apiData => shouldShowField(notice, {}, apiData);

    it('shows when the server reports the shared client is in use', () => {
        expect(show({ gdrive_credentials: { shared_client_id: true } })).toBe(true);
    });

    it('hides when the server reports real credentials', () => {
        expect(show({ gdrive_credentials: { shared_client_id: false } })).toBe(false);
    });

    it('shows even when a service-account path is set, if the server says shared', () => {
        expect(
            shouldShowField(
                notice,
                { gdrive_sa_location: '/config/missing.json', client_id: '' },
                { gdrive_credentials: { shared_client_id: true } }
            )
        ).toBe(true);
    });

    it('hides rather than false-alarms before the flag has loaded', () => {
        expect(show({})).toBe(false);
        expect(show({ gdrive_credentials: {} })).toBe(false);
        expect(shouldShowField(notice, {})).toBe(false);
    });

    it('treats a non-boolean flag as not set', () => {
        expect(show({ gdrive_credentials: { shared_client_id: 'true' } })).toBe(false);
        expect(show({ gdrive_credentials: { shared_client_id: 1 } })).toBe(false);
    });
});

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
