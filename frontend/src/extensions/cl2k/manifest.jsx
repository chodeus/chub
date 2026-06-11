// CL2K poster maker — self-registration manifest (develop-only extension).
// Discovered by src/extensions/index.js; see that file for the contract.
import React from 'react';
import { CL2K_MAKER_SCHEMA, CL2K_MAKER_MODULE_ENTRY } from './settings_schema.js';

const Cl2kMakerPage = React.lazy(() => import('../../pages/poster/Cl2kMakerPage.jsx'));

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
        // Extra Unmatched Assets row action: jump into the maker with the
        // row's ids prefilled. Only for rows with a TMDB id.
        'unmatchedAssets.rowAction': item =>
            item.tmdb_id
                ? {
                      to: `/poster/cl2k-maker?${new URLSearchParams({
                          tmdb_id: item.tmdb_id,
                          type: item._type,
                          title: item.title || '',
                          ...(item.year ? { year: item.year } : {}),
                          ...(item.tvdb_id ? { tvdb_id: item.tvdb_id } : {}),
                          ...(item.imdb_id ? { imdb_id: item.imdb_id } : {}),
                      }).toString()}`,
                      title: 'Make a CL2K poster',
                      ariaLabel: 'Make a CL2K poster',
                      icon: 'wallpaper',
                  }
                : null,
    },
};
