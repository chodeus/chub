import { describe, expect, it } from 'vitest';

import { resolveCheckWritable, shouldShowField } from './conditionalFields';
import { SETTINGS_SCHEMA } from '../constants/settings_schema.js';

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

// A move deletes the source file, so only then must CHUB be able to write a source folder.
describe('resolveCheckWritable', () => {
    const field = (moduleKey, key) =>
        SETTINGS_SCHEMA.find(m => m.key === moduleKey).fields.find(f => f.key === key);
    const posterSources = field('poster_renamerr', 'source_dirs');
    const assetSources = field('asset_renamerr', 'source_dirs');

    it.each([
        [{ apply_method: 'kometa', action_type: 'move' }, true],
        [{ action_type: 'move' }, true],
        [{ apply_method: 'kometa', action_type: 'copy' }, false],
        [{ apply_method: 'kometa', action_type: 'hardlink' }, false],
        [{ apply_method: 'plex', action_type: 'move' }, false],
        [{ apply_method: 'kometa', action_type: 'move', run_border_replacerr: true }, false],
    ])('checks poster source folders for %o: %s', (form, expected) => {
        expect(resolveCheckWritable(posterSources, form)).toBe(expected);
    });

    it.each([
        [{ apply_method: 'kometa', action_type: 'move' }, true],
        [{ apply_method: 'kometa', action_type: 'copy' }, false],
        [{ apply_method: 'plex', action_type: 'move' }, false],
    ])('checks asset source folders for %o: %s', (form, expected) => {
        expect(resolveCheckWritable(assetSources, form)).toBe(expected);
    });

    it('keeps an always-checked folder checked and an unchecked one unchecked', () => {
        const form = { apply_method: 'plex', action_type: 'copy' };
        expect(resolveCheckWritable(field('poster_renamerr', 'destination_dir'), form)).toBe(true);
        expect(resolveCheckWritable(field('asset_renamerr', 'tmdb_language'), form)).toBe(false);
    });
});
