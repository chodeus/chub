# Tailwind v4 Migration Plan — CHUB frontend

Status: **COMPLETE** (full port, on branch `spike/tailwind-v4`). 124 files changed, +1,563 / −8,197 (≈6,600 net lines of hand-rolled CSS removed). All legacy `src/css/utilities/` + `scripts/format-utilities.js` deleted.

## Outcome / how it actually went

- **Bespoke surface was tiny in practice.** The legacy library held ~1,996 selectors, but a dead-class audit (every `className` token across 167 files vs the compiled Tailwind output) found only **~24 used-but-unresolved**, and after the `@theme` map + ports, **0 real** (the remaining 11 are pre-existing-undefined classes — dead in legacy too — plus JS vars and the external `material-symbols-outlined`). Tailwind + `@theme` regenerated almost everything for free.
- **Codemod**: single pass over 99 files for the genuine collisions only — `text-primary→text-fg`, `text-secondary→text-fg-muted`, `text-tertiary→text-fg-subtle`, `*-contrast`, `bg-secondary→bg-surface-alt` (variant- and opacity-aware boundary: `hover:text-primary`, `bg-secondary/20` handled). `brand-primary`/`default`/`input-error` were `@theme`-aliased instead.
- **Value-mismatch audit** (the audit's blind spot — classes that resolve but with the *wrong* value): of 16 value-risky used classes, fixed **fonts** (custom `Roboto`/`Georgia`/`SF Mono` stacks via `@theme`) and the **box-shadow ring system** (`ring-1`/`ring-primary`/`focus:ring-primary` — Tailwind's `ring-primary` only sets a colour var and renders nothing, so ported the exact box-shadow rules). `shadow-xl`, `duration-*`, `leading-*`, `animate-*` matched Tailwind defaults; `transition-transform` resolved to the same 150ms.
- **Radius**: `--radius-*: initial` clears Tailwind's namespace (it collides with `tokens.css`'s component `--radius-*`), and `rounded-*` are ported as literal-value `@utility` matching `borders.css`.
- **Validation**: build + eslint + prettier + stylelint green; dead-class audit = 0 real; **main-vs-migrated computed-style diff on the dashboard was identical** (body/headings/text/buttons/sidebar); border-replacerr confirmed pixel-identical (spike) and re-confirmed in light + dark.
- **Known pre-existing dead** (out of scope, broken before too): `accordion-body`, `form-root`, `field-wrapper`, `bg-surface-disabled`, `placeholder-tertiary`, `color-picker-webkit-reset`, the vestigial `invalid` marker.

---

## (original plan follows)

## Why

The frontend is already authored in Tailwind-idiom class names (`flex items-center gap-3 p-4 bg-surface-alt hover:bg-surface-alt md:ml-auto`) but has **no Tailwind**. Utilities are a hand-authored static library in `src/css/utilities/` (~2,700 selectors, formatted by `scripts/format-utilities.js`). Because every `variant:base` permutation must be hand-written, classes that nobody pre-authored silently no-op. Verified dead-but-used across real pages today:

- `hover:underline`, `hover:text-accent`, `hover:bg-hover`, `hover:bg-error-hover`
- `focus:outline-primary`, `focus:outline-2`, `ring-primary/40` (focus rings don't render)
- `last:border-b-0`, `aspect-[2/3]` (arbitrary values unsupported)

Tailwind v4's JIT generates every valid utility + variant + arbitrary value on demand, and the IntelliSense/eslint plugin catches typos at author-time — eliminating the recurring bug class that commit `250fd3f` was spent cleaning up.

## Current-state facts (verified)

| Area | Finding |
|---|---|
| Toolchain | Vite `^8`, React `19.2`, Node `>=24.16` (26 installed), ESLint `9`, stylelint `17` → **Tailwind v4** (CSS-first, `@tailwindcss/vite`) |
| CSS entry | `src/main.jsx` → `import './css/index.css'` |
| `index.css` | `@import`s base → theme (tokens/dark/light) → components → utilities |
| Theming | `src/utils/theme.js:213` sets `data-theme` on `<html>`; `[data-theme='light'|'dark']` blocks, **52 tokens each**; `tokens.css` = theme-agnostic radius/fonts in `:root` |
| Numeric scale | **Already rem-based and Tailwind-identical** (`h-11`=2.75rem, `p-2`=0.5rem, `gap-3`=0.75rem) → numeric utilities map 1:1, no edits |
| Component CSS (PRESERVE) | `src/css/components/`: accordion, badges, hamburger-button, interactions, navigation, logs |
| Inline `<style>` (PRESERVE) | `LoginPage.jsx`, `SetupWizardPage.jsx` — self-contained, untouched by migration |
| Utilities (REPLACE) | entire `src/css/utilities/` |
| Scale | 2,959 `className` attrs across 167 `.jsx` files; most map 1:1 |

## The one hard problem: color-namespace collisions

Tailwind generates `bg-X`, `text-X`, `border-X`, `ring-X` from a single `--color-X`. The current system uses the **same word to mean different things** for `text-` vs `bg-`:

| Current class | Current value | Meaning |
|---|---|---|
| `bg-primary` | `var(--primary)` | brand indigo |
| `text-primary` | `var(--text-primary)` | **body text** (not brand) |
| `text-brand-primary` | `var(--primary)` | brand-colored text |
| `bg-secondary` | `var(--surface-alt)` | surface |
| `text-secondary` | `var(--text-secondary)` | muted body text |
| `text-tertiary` | `var(--text-tertiary)` | subtle body text |
| `text-on-color` / `text-primary-text` / `text-primary-contrast` | `var(--on-color-text)` | text on brand fill |

**Recommended resolution (needs sign-off — this is the only semantic decision):** adopt Tailwind's model where `primary` = brand everywhere, and rename body-text utilities to a `fg` family.

| New token (`@theme inline`) | Value | Enables |
|---|---|---|
| `--color-primary` | `var(--primary)` | `bg/text/border/ring-primary` = brand |
| `--color-fg` | `var(--text-primary)` | `text-fg` (body) |
| `--color-fg-muted` | `var(--text-secondary)` | `text-fg-muted` |
| `--color-fg-subtle` | `var(--text-tertiary)` | `text-fg-subtle` |
| `--color-on-color` | `var(--on-color-text)` | `text-on-color`, `bg-on-color` |

Codemod (mechanical, scriptable — only these tokens):
- `text-primary` → `text-fg`
- `text-secondary` → `text-fg-muted`
- `text-tertiary` → `text-fg-subtle`
- `text-brand-primary` → `text-primary`
- `bg-secondary` → `bg-surface-alt`
- `text-primary-text` | `text-primary-contrast` → `text-on-color`
- `bg-primary-hover` → `hover:bg-primary` (or keep as a custom `@utility` mapping to `--focus`)

Everything else (`bg-surface-alt`, `text-error`, `border-border`, `bg-success`, `bg-primary/15`, `bg-info/30`, `border-warning/40`, …) maps **1:1 with no edits**. Opacity modifiers (`/15`, `/30`) work natively in v4 — several currently-dead classes go live for free.

## `@theme` mapping (the config artifact)

A new `src/css/tailwind.css` (imported first in `index.css`), using `@theme inline` so utilities emit `var(--primary)` directly and keep switching per `[data-theme]`:

```css
@import "tailwindcss";

/* runtime theme vars still live in theme/light.css + dark.css unchanged */
@theme inline {
  /* brand + semantic (1:1, no collision) */
  --color-primary: var(--primary);
  --color-accent: var(--accent);
  --color-accent-2: var(--accent-2);
  --color-success: var(--success);
  --color-warning: var(--warning);
  --color-error: var(--error);
  --color-info: var(--info);
  --color-focus: var(--focus);

  /* surfaces */
  --color-bg: var(--bg);
  --color-surface: var(--surface);
  --color-surface-alt: var(--surface-alt);
  --color-surface-elevated: var(--surface-elevated);

  /* borders */
  --color-border: var(--border);
  --color-border-light: var(--border-light);

  /* text (renamed family — see codemod) */
  --color-fg: var(--text-primary);
  --color-fg-muted: var(--text-secondary);
  --color-fg-subtle: var(--text-tertiary);
  --color-on-color: var(--on-color-text);

  /* radius (override TW defaults with token values) */
  --radius-sm: 8px; --radius-md: 12px; --radius-lg: 16px;
  --radius-xl: 24px; --radius-full: 9999px;

  /* fonts */
  --font-display: var(--font-display);
  --font-body: var(--font-body);
}

/* attribute-based dark mode (project uses data-theme, not .dark) */
@custom-variant dark ([data-theme='dark'] &);

/* semantic z-index scale — ported as utilities */
@utility z-negative { z-index: -1; }
@utility z-sidebar  { z-index: 100; }
@utility z-dropdown { z-index: 200; }
@utility z-sticky   { z-index: 300; }
@utility z-fixed    { z-index: 400; }
@utility z-overlay  { z-index: 500; }
@utility z-modal-backdrop { z-index: 550; }
@utility z-modal    { z-index: 600; }
@utility z-popover  { z-index: 650; }
@utility z-notification { z-index: 700; }
@utility z-tooltip  { z-index: 800; }
@utility z-max      { z-index: 9999; }
/* (mirror exact values from utilities/zindex.css) */

/* bespoke utilities with no Tailwind equivalent */
@utility touch-target { /* copy from accessibility.css */ }
@utility scrollbar-hidden {
  scrollbar-width: none;
  -ms-overflow-style: none;
}
@utility scrollbar-hidden { &::-webkit-scrollbar { display: none; } }
```

Also map sidebar/badge/overlay/input tokens the same way as needed by audited usage (`bg-sidebar-*`, `bg-badge-*`, `bg-overlay`, `bg-input` → `--color-*`).

## Risks & mitigations

1. **Preflight (Tailwind's reset) vs `base.css`.** v4 Preflight zeroes margins, unstyles headings/lists, changes default borders → high regression risk. **Mitigation:** start WITHOUT Preflight (import only `theme`/`utilities` layers), keep existing `base.css`; evaluate adopting Preflight as a separate follow-up.
2. **Dead classes go live.** Focus rings, `hover:underline`, `aspect-[2/3]`, `ring-primary/40` will start rendering. Net-positive but *visual change* — must be reviewed, not assumed safe.
3. **Layer/specificity ordering.** Tailwind utilities sit in a low-priority `@layer`; unlayered component CSS (`components/*.css`, inline `<style>`) will override them. Where a utility currently beats component CSS, behavior may flip. **Mitigation:** wrap component CSS in `@layer components` (below utilities) or audit overrides during the spike.
4. **Non-scale px values** (`min-w-200`) need arbitrary syntax `min-w-[200px]`. Small, grep-able set.
5. **Codemod false hits.** `text-primary` etc. only appear as class tokens, but run the codemod scoped to `className` string contents and review the diff.
6. **stylelint config** targets the hand-written utilities; update/relax rules for generated CSS and the `@theme`/`@utility` at-rules.

## Phased execution

**Phase 0 — Spike (proves the approach; ~½ day)**
1. `npm i -D tailwindcss @tailwindcss/vite`; add the plugin to `vite.config.js`.
2. Create `src/css/tailwind.css` with the `@theme inline` map above (no Preflight); `@import` it first in `index.css`.
3. Convert **one representative page** (e.g. `pages/poster/BorderPreviewPage.jsx`) — run the color codemod on it only.
4. Capture before/after screenshots (visual-regression tooling is available) in light + dark.
5. **Gate:** diff is clean (or only the intended focus-ring/underline improvements). If not, revisit the mapping before rollout.

**Phase 1 — Foundation**
6. Finalize the full `@theme` map (audit every `bg-*`/`text-*`/`border-*` token actually used → ensure each has a `--color-*`).
7. Port `zindex`, `touch-target`, `scrollbar-hidden`, and any other bespoke utilities as `@utility`.
8. Add Tailwind IntelliSense settings + `eslint-plugin-tailwindcss` (or v4 equivalent) so invalid classes fail lint.

**Phase 2 — Codemod & cutover**
9. Run the color/`min-w-200` codemod across all 167 files; commit as one reviewable diff.
10. Delete `src/css/utilities/` and `scripts/format-utilities.js`; drop the `utilities/index.css` import; remove the `format:utilities` npm script.
11. `npm run lint`, `npm run stylelint`, `npx vite build` all green.

**Phase 3 — Verify**
12. Full visual-regression sweep across key pages × {light, dark} — triage every diff into intended vs regression.
13. Manually exercise focus states / hover states that were previously dead.
14. Re-run the dead-class audit (the calibrated script) → expect **zero** dead utility tokens.

**Phase 4 — Land**
15. Conventional commits so it actually releases:
    - `build(deps): add tailwindcss v4 + vite plugin`
    - `refactor(css): map design tokens to @theme; port bespoke utilities`
    - `refactor(css): codemod color/text utility names to Tailwind namespace`
    - `feat(css): replace hand-rolled utilities with Tailwind v4` (this triggers the release + container build)
    - `chore(css): remove legacy utility library and formatter`

## Rollback

Each phase is an isolated commit; the legacy `src/css/utilities/` deletion is the last code step. Revert the deletion commit (or the whole branch) to restore the old system instantly — the `@theme` additions are inert without the utilities removed only if class names changed, so rollback = revert the branch.

## Effort

Bounded. The 1:1 numeric/semantic mapping removes ~90% of risk; real work is (a) the `@theme` token map, (b) the small color codemod, (c) the visual-regression triage. Spike first, decide go/no-go on real diffs.

## Spike findings (Phase 0 — completed on `spike/tailwind-v4`)

Ran the spike end-to-end on `BorderPreviewPage.jsx`. Outcome: **feasible, build/lint/prettier/stylelint all green.** Hard-won gotchas to bake into execution:

1. **Tailwind's CSS entry MUST be a JS import, not a nested `@import url()`.** `@tailwindcss/vite` only treats a directly-imported CSS file as a Tailwind root. Reaching `tailwind.css` via `@import url('./tailwind.css')` from `index.css` silently produced **zero utilities** (theme vars still emitted, masking it). Fix: `import './css/tailwind.css'` in `main.jsx` before `index.css`.
2. **Add an explicit `@source`.** Auto content-detection missed `src/` (git root is a level above `frontend/`). `@source '../**/*.{jsx,js}'` in `tailwind.css` fixes it.
3. **Don't reference `--text-*` source vars under `@theme inline`** — `--text-*` is Tailwind's font-size namespace and the collision suppressed the utility. Plain `@theme` (non-inline) works; theme switching still works because `var(--token)` resolves lazily at use-site under `[data-theme]`. (Drop self-referential `--font-*` lines if non-inline.)
4. **stylelint needs a Tailwind-aware override** for `tailwind.css` (`at-rule-no-unknown` ignore list for `theme`/`utility`/`source`/`custom-variant`, plus `import-notation: null`). Added to `stylelint.config.js`.
5. **Codemod confirmed faithful**: `text-primary→text-fg`, `text-secondary→text-fg-muted`, `text-tertiary→text-fg-subtle`, `bg-error-bg→bg-error/10`, `bg-warning-bg→bg-warning/10`, `border-error-border→border-error` — each maps to the identical CSS-variable value, so output is equivalent by construction.
6. **CRITICAL — CSS `@layer` ordering caused a global regression.** base.css declares `@layer reset, base, components, utilities, pages` (resets lowest), and the legacy utility files wrap rules in `@layer utilities`. My `tailwind.css` (loaded first) declared `@layer theme, base, components, utilities` **without `reset`** — so when base.css later named `reset`, it was appended *after* `utilities`, inverting the cascade. The `img { height: auto }` reset then beat `.h-16`, blowing the header logo up to natural size **app-wide**. Fix: declare the full order including `reset`/`pages` in tailwind.css: `@layer reset, theme, base, components, utilities, pages;`. This is the #1 migration risk in practice — confirmed and fixed in the spike.

### Visual verification done (live, on the dev server)
Ran the frontend with no backend (auth gate opens when `authConfigured` is false; page renders its error state). Verified the converted element via `preview_inspect` computed styles — **before (legacy) vs after (Tailwind) are byte-identical**: `color`/`border` `rgb(253,53,92)` (`--error`), background `color(srgb … / 0.1)` (10% mix), radius `8px`. Confirmed in **light and dark** (`[data-theme]` switching intact) and that `text-fg-subtle` resolves to `#5f446b` (`--text-tertiary`). Logo regression caught and fixed here (64px restored with Tailwind on).

**Still not done:** a data-rich screenshot of the full page (needs the backend on `:8000` + real Border Replacerr config). The error-state render + computed-style equivalence is strong evidence; a live-instance pass is the final confirmation.
