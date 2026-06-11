// Discovery point for self-registering frontend extensions.
//
// An extension is a folder under src/extensions/<name>/ with a manifest.jsx
// default-exporting an object; every field is optional:
//
//   routes: [{ path, pageName, pageDescription, Component }]
//       Mounted by App.jsx inside the authed layout, each wrapped in a
//       PageErrorBoundary (Component is typically React.lazy).
//   navChildren: [{ parentId, before?, item }]
//       Sidebar children spliced into NAV_SECTIONS under the parent item
//       with id === parentId, before the child id `before` (or appended).
//   settingsSchema: [{ after?, before?, entry }]
//       Module blocks spliced into SETTINGS_SCHEMA anchored on a core key.
//   settingsModules: [{ after?, before?, entry }]
//       Entries spliced into SETTINGS_MODULES the same way.
//   configModules: [{ after?, before?, key }]
//       Keys spliced into useModuleSchema's CONFIG_MODULE_KEYS.
//   capabilities: { [name]: value }
//       Named hooks core pages can query via extensionCapability(name) —
//       e.g. a function that builds an extra action for a table row.
//
// With no extension folders present (main) every aggregate below is empty
// and the consumers render exactly as if this module did not exist.

const manifestModules = import.meta.glob('./*/manifest.jsx', { eager: true });
const MANIFESTS = Object.values(manifestModules)
    .map(mod => mod.default)
    .filter(Boolean);

/**
 * Splice anchored additions into a copy of `list`.
 * Each addition is { entry, after?: anchor, before?: anchor }; `keyOf` maps a
 * list element to the identifier anchors refer to. Unanchored or unmatched
 * additions are appended.
 */
export function spliceByAnchor(list, additions, keyOf) {
    const result = [...list];
    for (const { entry, after, before } of additions) {
        let index = result.length;
        if (after != null) {
            const at = result.findIndex(el => keyOf(el) === after);
            if (at !== -1) index = at + 1;
        } else if (before != null) {
            const at = result.findIndex(el => keyOf(el) === before);
            if (at !== -1) index = at;
        }
        result.splice(index, 0, entry);
    }
    return result;
}

export function extensionRoutes() {
    return MANIFESTS.flatMap(m => m.routes ?? []);
}

/** NAV_SECTIONS with every extension's navChildren spliced in. */
export function withExtensionNavChildren(sections) {
    const additions = MANIFESTS.flatMap(m => m.navChildren ?? []);
    if (additions.length === 0) return sections;
    return sections.map(section => ({
        ...section,
        items: section.items.map(item => {
            const mine = additions.filter(a => a.parentId === item.id);
            if (mine.length === 0 || !item.children) return item;
            return {
                ...item,
                children: spliceByAnchor(
                    item.children,
                    mine.map(({ before, after, item: child }) => ({
                        entry: child,
                        before,
                        after,
                    })),
                    child => child.id
                ),
            };
        }),
    }));
}

export function withExtensionSettingsSchema(schema) {
    const additions = MANIFESTS.flatMap(m => m.settingsSchema ?? []);
    return additions.length ? spliceByAnchor(schema, additions, el => el.key) : schema;
}

export function withExtensionSettingsModules(modules) {
    const additions = MANIFESTS.flatMap(m => m.settingsModules ?? []);
    return additions.length ? spliceByAnchor(modules, additions, el => el.key) : modules;
}

export function withExtensionConfigModuleKeys(keys) {
    const additions = MANIFESTS.flatMap(m => m.configModules ?? []);
    return additions.length
        ? spliceByAnchor(
              keys,
              additions.map(({ key, after, before }) => ({ entry: key, after, before })),
              k => k
          )
        : keys;
}

/** First extension-provided value registered under `name`, or null. */
export function extensionCapability(name) {
    for (const manifest of MANIFESTS) {
        const value = manifest.capabilities?.[name];
        if (value != null) return value;
    }
    return null;
}
