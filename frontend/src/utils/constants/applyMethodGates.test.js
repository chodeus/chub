/** Guards which Poster/Asset Renamerr fields each apply method shows (real schema + the page's filter). */
import { SETTINGS_SCHEMA } from './settings_schema.js';
import { shouldShowField } from '../forms/conditionalFields.js';

const KOMETA_FIELDS = ['action_type', 'destination_dir', 'asset_folders'];
const PLEX_FIELDS = ['upload_delay_ms', 'skip_unchanged_uploads'];

const visibleKeys = (moduleKey, moduleData) =>
    SETTINGS_SCHEMA.find(m => m.key === moduleKey)
        .fields.filter(f => shouldShowField(f, moduleData, {}))
        .map(f => f.key);

describe.each(['poster_renamerr', 'asset_renamerr'])('%s apply-method gates', moduleKey => {
    it.each([
        ['kometa', { apply_method: 'kometa' }],
        ['unset (backend default kometa)', {}],
    ])('%s shows the Kometa output fields and hides Plex-only ones', (_, data) => {
        const keys = visibleKeys(moduleKey, data);

        expect(keys).toEqual(expect.arrayContaining(KOMETA_FIELDS));
        PLEX_FIELDS.forEach(k => expect(keys).not.toContain(k));
    });

    it('plex hides the Kometa output fields', () => {
        const keys = visibleKeys(moduleKey, { apply_method: 'plex' });

        KOMETA_FIELDS.forEach(k => expect(keys).not.toContain(k));
        expect(keys).toEqual(expect.arrayContaining(['apply_method', 'plex_scope']));
    });
});

it('Poster Renamerr shows its Plex-only upload settings for the Plex method', () => {
    expect(visibleKeys('poster_renamerr', { apply_method: 'plex' })).toEqual(
        expect.arrayContaining(PLEX_FIELDS)
    );
});

it('Poster Renamerr offers orphan cleanup only for Kometa, where the run performs it', () => {
    expect(visibleKeys('poster_renamerr', { apply_method: 'kometa' })).toContain(
        'clean_orphan_assets'
    );
    expect(visibleKeys('poster_renamerr', { apply_method: 'plex' })).not.toContain(
        'clean_orphan_assets'
    );
});
