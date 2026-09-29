import { readFileSync } from 'node:fs';
import { ACCENTS } from '../../contexts/ThemeContext.jsx';

const TEXT_TOKENS = [
    'success',
    'warning',
    'error',
    'info',
    'text-primary',
    'text-secondary',
    'text-tertiary',
    'service-radarr',
    'service-sonarr',
    'service-lidarr',
    'service-plex',
    'source-gdrive',
    'source-local',
    'source-cl2k',
    'source-orphan',
    'accent',
    'method-discord',
    'method-notifiarr',
];
const SOLID_FILLS = ['success', 'warning', 'info', 'error', 'accent'];
const TINTED_TEXT = [
    'success',
    'warning',
    'error',
    'info',
    'accent',
    'source-gdrive',
    'source-local',
    'source-cl2k',
    'source-orphan',
    'method-discord',
    'method-notifiarr',
];
const RESTING_SURFACES = ['bg', 'surface', 'surface-alt', 'surface-elevated'];
const CHROME_TEXT = ['sidebar-text', 'sidebar-text-secondary', 'sidebar-heading'];
const CHROME_SURFACES = ['sidebar-bg', 'header-bg'];
const MARKERS = ['text-faint'];

const rgb = hex => {
    const digits = hex.length === 4 ? [...hex.slice(1)].map(d => d + d) : hex.slice(1).match(/../g);
    return digits.map(d => parseInt(d, 16));
};

// Theme block only: the prefers-contrast override further down redefines some tokens.
const readTokens = file => {
    const css = readFileSync(new URL(file, import.meta.url), 'utf8');
    const block = css.slice(0, css.indexOf('@media'));
    return Object.fromEntries(
        [...block.matchAll(/--([\w-]+):\s*(#[0-9a-f]{3,6})\b/gi)].map(([, name, hex]) => [
            name,
            rgb(hex),
        ])
    );
};

const luminance = color => {
    const [r, g, b] = color.map(v => {
        const c = v / 255;
        return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

// What `color-mix(in srgb, fg <share>, transparent)` shows once painted over bg.
const tint = (fg, share, bg) => fg.map((v, i) => v * share + bg[i] * (1 - share));

const contrast = (a, b) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
};

const expectReadable = (fg, bg, label) =>
    expect(contrast(fg, bg), label).toBeGreaterThanOrEqual(4.5);

const expectVisible = (fg, bg, label) => expect(contrast(fg, bg), label).toBeGreaterThanOrEqual(3);

describe.each([
    ['dark', './dark.css'],
    ['light', './light.css'],
])('%s theme', (_, file) => {
    const tokens = readTokens(file);

    it.each(SOLID_FILLS)('--on-%s clears 4.5:1 on its solid fill', fill => {
        expectReadable(tokens[`on-${fill}`], tokens[fill], `--on-${fill} on --${fill}`);
    });

    it.each(TEXT_TOKENS)('--%s clears 4.5:1 as text on every resting surface', token => {
        for (const surface of RESTING_SURFACES) {
            expectReadable(tokens[token], tokens[surface], `--${token} on --${surface}`);
        }
    });

    it.each(CHROME_TEXT)('--%s clears 4.5:1 on the sidebar and header', token => {
        for (const surface of CHROME_SURFACES) {
            expectReadable(tokens[token], tokens[surface], `--${token} on --${surface}`);
        }
    });

    // Pills and badges set a colour's text on a 20% tint of itself.
    it.each(TINTED_TEXT)('--%s clears 4.5:1 on its own tint over every resting surface', token => {
        for (const surface of RESTING_SURFACES) {
            const ownTint = tint(tokens[token], 0.2, tokens[surface]);
            expectReadable(tokens[token], ownTint, `--${token} on its tint over --${surface}`);
        }
    });

    // Idle dots and markers show state, so they need 3:1 (WCAG 1.4.11).
    it.each(MARKERS)('--%s clears 3:1 as a marker on every resting surface', token => {
        for (const surface of RESTING_SURFACES) {
            expectVisible(tokens[token], tokens[surface], `--${token} on --${surface}`);
        }
    });
});

// Dark shades are the brand fills (white on Violet and Azure is a brand call), so only their text hover is checked.
describe.each(Object.keys(ACCENTS))('%s accent', key => {
    const light = readTokens('./light.css');
    const dark = readTokens('./dark.css');
    const shades = theme =>
        Object.fromEntries(Object.entries(ACCENTS[key][theme]).map(([k, hex]) => [k, rgb(hex)]));

    it('light shades read as text, on their own tint and under their ink', () => {
        const { brand, hover, onBrand } = shades('light');
        expectReadable(onBrand, brand, 'onBrand on brand');
        for (const surface of RESTING_SURFACES) {
            const brandTint = tint(brand, 0.2, light[surface]);
            expectReadable(brand, light[surface], `brand on --${surface}`);
            expectReadable(brand, brandTint, `brand on its tint over --${surface}`);
            expectReadable(hover, light[surface], `hover on --${surface}`);
            expectReadable(hover, brandTint, `hover on the brand tint over --${surface}`);
        }
    });

    // Bare text-primary is kept to icons (classGuards.test.js), which need 3:1.
    it('dark brand clears 3:1 as an icon on every resting surface', () => {
        const { brand } = shades('dark');
        for (const surface of RESTING_SURFACES) {
            expectVisible(brand, dark[surface], `brand on --${surface}`);
        }
    });

    // Accent text on an accent tint (bg-primary/15 text-primary-hover) uses the hover shade.
    it('dark text hover reads on every resting surface and on the brand tint', () => {
        const { brand, hover } = shades('dark');
        for (const surface of RESTING_SURFACES) {
            const brandTint = tint(brand, 0.2, dark[surface]);
            expectReadable(hover, dark[surface], `hover on --${surface}`);
            expectReadable(hover, brandTint, `hover on the brand tint over --${surface}`);
        }
    });
});

// The stylesheets paint the default accent before ThemeContext applies one, so they must hold Violet.
it.each([
    ['dark', './dark.css'],
    ['light', './light.css'],
])('%s stylesheet defaults match the Violet accent', (theme, file) => {
    const tokens = readTokens(file);
    const { violet } = ACCENTS;
    expect(tokens.primary).toEqual(rgb(violet[theme].brand));
    expect(tokens['primary-hover']).toEqual(rgb(violet[theme].hover));
    expect(tokens['on-color-text']).toEqual(rgb(violet[theme].onBrand));
    expect(tokens['sidebar-accent']).toEqual(rgb(violet.dark.brand));
    expect(tokens['sidebar-on-accent']).toEqual(rgb(violet.dark.onBrand));
});
