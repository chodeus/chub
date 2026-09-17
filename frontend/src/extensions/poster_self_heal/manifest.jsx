// Poster Self-Heal — self-registration manifest (':full'-image extension).
// Discovered by src/extensions/index.js; see that file for the contract.
import React from 'react';
import { FieldRegistry } from '../../components/fields/FieldRegistry.jsx';
import { POSTER_SELF_HEAL_SCHEMA, POSTER_SELF_HEAL_MODULE_ENTRY } from './settings_schema.js';
import { PosterSelfHealCoverageField } from './CoverageField.jsx';

// Registered at module scope — manifests are eagerly imported at app init, so
// the type exists before ModuleSettingsPage first resolves it.
FieldRegistry.register('poster_self_heal_coverage', PosterSelfHealCoverageField);

const PosterHealReviewPage = React.lazy(
    () => import('../../pages/poster/PosterHealReviewPage.jsx')
);

export default {
    routes: [
        {
            path: 'poster/heal-review',
            pageName: 'Poster Healer Review',
            pageDescription:
                'Review and apply proposed id / title / year fixes for your CL2K posters',
            Component: PosterHealReviewPage,
        },
    ],
    // Without this the page is reachable only from a CL2K Maker badge shown when the
    // open count is non-zero — a run reporting work left could point nowhere.
    navChildren: [
        {
            parentId: 'poster',
            before: 'unmatched-assets',
            item: {
                id: 'poster-heal-review',
                label: 'Poster Healer Review',
                path: '/poster/heal-review',
            },
        },
    ],
    // Anchored after a core module (always present) rather than cl2k_maker, so it
    // doesn't depend on another extension's splice having run first.
    settingsSchema: [{ after: 'border_replacerr', entry: POSTER_SELF_HEAL_SCHEMA }],
    settingsModules: [{ after: 'border_replacerr', entry: POSTER_SELF_HEAL_MODULE_ENTRY }],
    configModules: [{ after: 'border_replacerr', key: 'poster_self_heal' }],
};
