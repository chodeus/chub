// CL2K poster maker — self-registration manifest (':full'-image extension).
// Discovered by src/extensions/index.js; see that file for the contract.
import React from 'react';
import { FieldRegistry } from '../../components/fields/FieldRegistry.jsx';
import { CL2K_MAKER_SCHEMA, CL2K_MAKER_MODULE_ENTRY } from './settings_schema.js';
import { Cl2kAiTestField } from './AiConnectionTest.jsx';
import {
    Cl2kCoverageField,
    Cl2kGdriveUploadsField,
    Cl2kLocalFoldersField,
} from './SaveLocationsFields.jsx';

const Cl2kMakerPage = React.lazy(() => import('../../pages/poster/Cl2kMakerPage.jsx'));

// Registered at module scope: manifests are eagerly imported at app init, so these
// types exist before ModuleSettingsPage first resolves them.
FieldRegistry.register('cl2k_local_folders', Cl2kLocalFoldersField);
FieldRegistry.register('cl2k_gdrive_uploads', Cl2kGdriveUploadsField);
FieldRegistry.register('cl2k_coverage', Cl2kCoverageField);
FieldRegistry.register('cl2k_ai_test', Cl2kAiTestField);

export default {
    routes: [
        {
            path: 'poster/cl2k-maker',
            pageName: 'CL2K Poster Maker',
            pageDescription:
                'Build DAPS-named CL2K posters from TMDB/fanart art, .psd sources, or uploads',
            Component: Cl2kMakerPage,
        },
    ],
    navChildren: [
        {
            parentId: 'poster',
            before: 'unmatched-assets',
            item: {
                id: 'cl2k-maker',
                label: 'CL2K Poster Maker',
                path: '/poster/cl2k-maker',
            },
        },
    ],
    settingsSchema: [{ after: 'border_replacerr', entry: CL2K_MAKER_SCHEMA }],
    settingsModules: [{ after: 'border_replacerr', entry: CL2K_MAKER_MODULE_ENTRY }],
    configModules: [{ after: 'border_replacerr', key: 'cl2k_maker' }],
    capabilities: {
        // Shown whenever the row has ANY of tmdb/tvdb/imdb, so a TVDB-only Sonarr show
        // still gets the link. The optional `asset` arg picks the maker tab to open.
        'unmatchedAssets.rowAction': (item, asset) => {
            if (!(item.tmdb_id || item.tvdb_id || item.imdb_id)) return null;
            const ASSET_TAB = { background: 'background', logo: 'logo', squareart: 'square' };
            const tab = ASSET_TAB[asset];
            return {
                to: `/poster/cl2k-maker?${new URLSearchParams({
                    ...(item.tmdb_id ? { tmdb_id: item.tmdb_id } : {}),
                    type: item._type,
                    title: item.title || '',
                    ...(item.year ? { year: item.year } : {}),
                    ...(item.tvdb_id ? { tvdb_id: item.tvdb_id } : {}),
                    ...(item.imdb_id ? { imdb_id: item.imdb_id } : {}),
                    ...(tab ? { asset: tab } : {}),
                }).toString()}`,
                title: tab ? 'Build this artwork in CL2K' : 'Make a CL2K poster',
                ariaLabel: tab ? 'Build this artwork in CL2K' : 'Make a CL2K poster',
                icon: 'wallpaper',
            };
        },
    },
};
