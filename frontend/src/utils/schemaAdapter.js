/**
 * Schema Adapter — converts Pydantic JSON Schema into the
 * SETTINGS_SCHEMA field format used by ModuleSettingsPage.
 *
 * Backend returns JSON Schema (types: string, integer, boolean, array, object).
 * Frontend expects field definitions with: key, label, type, options, description, etc.
 */

// Fields whose names indicate they hold secrets
const SECRET_FIELD_PATTERNS = [/^api$/, /api[_-]?key/i, /secret/i, /token/i, /password/i];

// Fields that should be rendered as log-level dropdowns
const LOG_LEVEL_FIELDS = ['log_level'];
const LOG_LEVEL_OPTIONS = ['debug', 'info', 'warning', 'error'];

/**
 * Convert a snake_case key to a human-readable label.
 * e.g. 'source_dirs' -> 'Source Dirs'
 */
function keyToLabel(key) {
    return key
        .split('_')
        .map(w => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ');
}

/**
 * Determine whether a field name likely holds a secret.
 */
function isSecretField(key) {
    return SECRET_FIELD_PATTERNS.some(p => p.test(key));
}

/**
 * Resolve a $ref in a JSON schema definitions map.
 */
function resolveRef(ref, definitions) {
    if (!ref) return null;
    const refName = ref.replace('#/$defs/', '').replace('#/definitions/', '');
    return definitions?.[refName] || null;
}

/**
 * Convert a single JSON Schema property to a frontend field definition.
 *
 * @param {string} key - Property name
 * @param {Object} prop - JSON Schema property definition
 * @param {Object} definitions - Schema $defs for resolving $ref
 * @param {Object} uiHints - Optional UI hints overlay for this field
 * @returns {Object} Frontend field definition
 */
function propertyToField(key, prop, definitions = {}, uiHints = {}) {
    const hint = uiHints[key] || {};
    const field = {
        key,
        label: hint.label || keyToLabel(key),
        description: hint.description || prop.description || '',
        required: false,
    };

    if (hint.placeholder) field.placeholder = hint.placeholder;

    // Log level dropdown
    if (LOG_LEVEL_FIELDS.includes(key)) {
        field.type = 'dropdown';
        field.options = LOG_LEVEL_OPTIONS;
        return field;
    }

    // Secret fields
    if (isSecretField(key)) {
        field.type = 'password';
        return field;
    }

    // Enum -> dropdown
    if (prop.enum) {
        field.type = 'dropdown';
        field.options = prop.enum;
        return field;
    }

    // anyOf / oneOf with enum
    const anyOf = prop.anyOf || prop.oneOf;
    if (anyOf) {
        const enumVariant = anyOf.find(v => v.enum);
        if (enumVariant) {
            field.type = 'dropdown';
            field.options = enumVariant.enum;
            return field;
        }
    }

    // Resolve $ref
    let resolved = prop;
    if (prop.$ref) {
        resolved = resolveRef(prop.$ref, definitions) || prop;
    }

    const schemaType = resolved.type || (resolved.anyOf ? 'anyOf' : '');

    switch (schemaType) {
        case 'boolean':
            field.type = 'toggle';
            break;

        case 'integer':
        case 'number':
            field.type = 'number';
            break;

        case 'string':
            field.type = 'text';
            break;

        case 'array': {
            const items = resolved.items || {};
            if (items.$ref) {
                const itemSchema = resolveRef(items.$ref, definitions);
                if (itemSchema && itemSchema.type === 'object') {
                    field.type = 'array-object';
                    field.fields = objectPropertiesToFields(itemSchema, definitions, uiHints);
                } else {
                    field.type = 'array';
                }
            } else if (items.type === 'object') {
                field.type = 'array-object';
                field.fields = objectPropertiesToFields(items, definitions, uiHints);
            } else {
                field.type = 'array';
            }
            break;
        }

        case 'object':
            field.type = 'json';
            break;

        default:
            // anyOf with mixed types — treat as text
            field.type = 'text';
    }

    return field;
}

/**
 * Convert object properties to an array of field definitions.
 */
function objectPropertiesToFields(schema, definitions = {}, uiHints = {}) {
    const props = schema.properties || {};
    return Object.entries(props).map(([key, prop]) =>
        propertyToField(key, prop, definitions, uiHints)
    );
}

/**
 * Convert a full Pydantic JSON Schema (for one module) to a
 * SETTINGS_SCHEMA-compatible module entry.
 *
 * @param {string} moduleKey - Module key (e.g. 'sync_gdrive')
 * @param {Object} jsonSchema - Pydantic model JSON schema
 * @param {Object} uiHints - Optional UI hints for this module
 * @returns {Object} { key, label, fields: [...] }
 */
export function adaptModuleSchema(moduleKey, jsonSchema, uiHints = {}) {
    const definitions = jsonSchema.$defs || jsonSchema.definitions || {};
    const fields = objectPropertiesToFields(jsonSchema, definitions, uiHints);

    return {
        key: moduleKey,
        label: keyToLabel(moduleKey),
        fields,
    };
}

/**
 * Merge backend-derived schemas with the static fallback.
 * Backend schemas take priority; static entries fill gaps.
 *
 * @param {Array} backendSchemas - Array of { key, label, fields } from adaptModuleSchema
 * @param {Array} staticSchemas - SETTINGS_SCHEMA from constants
 * @returns {Array} Merged schema array
 */
export function mergeSchemas(backendSchemas, staticSchemas, orderedKeys = null) {
    const merged = [];
    const seen = new Set();
    const staticByKey = new Map(staticSchemas.map(s => [s.key, s]));

    // For each backend schema, merge at the field level with the static schema
    for (const backendSchema of backendSchemas) {
        const staticSchema = staticByKey.get(backendSchema.key);
        if (staticSchema) {
            // Static schema exists — use it as the base (it has UI-tuned field types
            // like dirlist_options, instances, etc. that the auto-generated backend
            // schema doesn't know about). Add any backend-only fields that the static
            // schema doesn't cover.
            const staticFieldKeys = new Set((staticSchema.fields || []).map(f => f.key));
            const extraFields = (backendSchema.fields || []).filter(
                f => !staticFieldKeys.has(f.key)
            );
            merged.push({
                ...staticSchema,
                fields: [...(staticSchema.fields || []), ...extraFields],
            });
        } else {
            // No static schema — use backend schema as-is
            merged.push(backendSchema);
        }
        seen.add(backendSchema.key);
    }

    // Fill in any static-only modules
    for (const schema of staticSchemas) {
        if (!seen.has(schema.key)) {
            merged.push(schema);
        }
    }

    // Sort by canonical order if provided
    if (orderedKeys) {
        const keyOrder = new Map(orderedKeys.map((k, i) => [k, i]));
        merged.sort((a, b) => {
            const idxA = keyOrder.has(a.key) ? keyOrder.get(a.key) : Infinity;
            const idxB = keyOrder.has(b.key) ? keyOrder.get(b.key) : Infinity;
            return idxA - idxB;
        });
    }

    return merged;
}
