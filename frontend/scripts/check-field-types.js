#!/usr/bin/env node
/**
 * Verifies every field `type:` string declared in settings_schema.js is known
 * to FieldRegistry.jsx. Prevents the regression where a new field type ships
 * in the schema but the bundle has no renderer for it (see object_array
 * regression, 2026-04-19).
 *
 * Run as part of `npm run lint` so CI fails before the image gets built.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SCHEMA_PATH = path.resolve(__dirname, '../src/utils/constants/settings_schema.js');
const REGISTRY_PATH = path.resolve(__dirname, '../src/components/fields/FieldRegistry.jsx');

const read = p => fs.readFileSync(p, 'utf8');

const extractSchemaTypes = src => {
    const types = new Set();
    const re = /type:\s*['"]([\w-]+)['"]/g;
    let match;
    while ((match = re.exec(src)) !== null) {
        types.add(match[1]);
    }
    return types;
};

const extractRegistryTypes = src => {
    // Pull keys out of FIELD_RESOLVERS (new lazy table).
    const resolversBlock = src.match(/const FIELD_RESOLVERS\s*=\s*{([\s\S]*?)^};/m);
    const types = new Set();
    if (resolversBlock) {
        const keyRe = /(?:^|\n)\s*(?:'([\w-]+)'|"([\w-]+)"|([\w-]+)):/g;
        let match;
        while ((match = keyRe.exec(resolversBlock[1])) !== null) {
            const key = match[1] || match[2] || match[3];
            if (key) types.add(key);
        }
    }
    // Also absorb the IMPLEMENTED_FIELD_TYPES Set entries for completeness.
    const implBlock = src.match(/IMPLEMENTED_FIELD_TYPES\s*=\s*new Set\(\[([\s\S]*?)\]\)/);
    if (implBlock) {
        const entryRe = /['"]([\w-]+)['"]/g;
        let match;
        while ((match = entryRe.exec(implBlock[1])) !== null) {
            types.add(match[1]);
        }
    }
    return types;
};

const schemaSrc = read(SCHEMA_PATH);
const registrySrc = read(REGISTRY_PATH);

const schemaTypes = extractSchemaTypes(schemaSrc);
const registryTypes = extractRegistryTypes(registrySrc);

const unknown = [...schemaTypes].filter(t => !registryTypes.has(t));

if (unknown.length > 0) {
    console.error(
        '\n✖ settings_schema.js references field type(s) not known to FieldRegistry:\n'
    );
    for (const t of unknown) {
        console.error(`  - ${t}`);
    }
    console.error(
        '\nAdd a resolver in FIELD_RESOLVERS and include the key in IMPLEMENTED_FIELD_TYPES.\n'
    );
    process.exit(1);
}

console.log(
    `✓ settings_schema field types all registered (${schemaTypes.size} types verified).`
);
