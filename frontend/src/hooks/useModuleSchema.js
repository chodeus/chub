import { useState, useEffect, useCallback } from 'react';
import { modulesAPI } from '../utils/api/modules.js';
import { adaptModuleSchema, mergeSchemas } from '../utils/schemaAdapter.js';
import { SETTINGS_SCHEMA } from '../utils/constants/settings_schema.js';

/**
 * Known config module keys that have Pydantic models on the backend.
 * Matches the fields in ChubConfig (backend/util/config.py).
 */
const CONFIG_MODULE_KEYS = [
    'general',
    'sync_gdrive',
    'poster_renamerr',
    'border_replacerr',
    'upgradinatorr',
    'renameinatorr',
    'nohl',
    'labelarr',
    'health_checkarr',
    'jduparr',
    'nestarr',
    'poster_cleanarr',
    'unmatched_assets',
];

/**
 * Hook that fetches module schemas from the backend and merges them
 * with the static SETTINGS_SCHEMA as a fallback.
 *
 * @returns {{ schemas: Array, loading: boolean, error: string|null }}
 */
// Sort the static fallback up-front so the initial render uses the same
// canonical order as the eventual backend merge. Otherwise General renders
// last for the first paint and pops to the top once the schemas resolve.
const SORTED_SETTINGS_SCHEMA = (() => {
    const keyOrder = new Map(CONFIG_MODULE_KEYS.map((k, i) => [k, i]));
    return [...SETTINGS_SCHEMA].sort((a, b) => {
        const idxA = keyOrder.get(a.key) ?? Infinity;
        const idxB = keyOrder.get(b.key) ?? Infinity;
        return idxA - idxB;
    });
})();

export function useModuleSchema() {
    const [schemas, setSchemas] = useState(SORTED_SETTINGS_SCHEMA);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Core fetch logic returned as a promise so all setState happens in .then/.catch
    // callbacks (not synchronously in any effect body).
    const fetchSchemas = useCallback(
        () =>
            Promise.allSettled(
                CONFIG_MODULE_KEYS.map(key =>
                    modulesAPI
                        .getModuleSchema(key)
                        .then(res => ({ key, schema: res?.data?.schema }))
                )
            )
                .then(results => {
                    const backendSchemas = results
                        .filter(r => r.status === 'fulfilled' && r.value.schema)
                        .map(r => adaptModuleSchema(r.value.key, r.value.schema));

                    // Re-sort to match CONFIG_MODULE_KEYS order (Promise.allSettled
                    // resolves in arbitrary order which causes modules to jump around)
                    const keyOrder = new Map(CONFIG_MODULE_KEYS.map((k, i) => [k, i]));
                    backendSchemas.sort((a, b) => {
                        const idxA = keyOrder.get(a.key) ?? Infinity;
                        const idxB = keyOrder.get(b.key) ?? Infinity;
                        return idxA - idxB;
                    });

                    if (backendSchemas.length > 0) {
                        setSchemas(
                            mergeSchemas(backendSchemas, SETTINGS_SCHEMA, CONFIG_MODULE_KEYS)
                        );
                    }
                    // If all fetches failed, we keep the static fallback
                })
                .catch(e => {
                    setError(e.message);
                    // Keep static schemas as fallback
                })
                .finally(() => {
                    setLoading(false);
                }),
        []
    );

    useEffect(() => {
        fetchSchemas();
    }, [fetchSchemas]);

    return { schemas, loading, error, refetch: fetchSchemas };
}
