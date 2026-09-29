import { readFileSync } from 'node:fs';

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
];
const RESTING_SURFACES = ['bg', 'surface', 'surface-alt'];

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

describe.each([
    ['dark', './dark.css'],
    ['light', './light.css'],
])('%s theme', (_, file) => {
    const tokens = readTokens(file);

    it.each(SOLID_FILLS)('--on-%s clears 4.5:1 on its solid fill', fill => {
        expect(contrast(tokens[`on-${fill}`], tokens[fill])).toBeGreaterThanOrEqual(4.5);
    });

    it.each(TEXT_TOKENS)('--%s clears 4.5:1 as text on every resting surface', token => {
        for (const surface of RESTING_SURFACES) {
            expect(
                contrast(tokens[token], tokens[surface]),
                `--${token} on --${surface}`
            ).toBeGreaterThanOrEqual(4.5);
        }
    });
});

// Pills and badges set a colour's text on a 20% tint of itself. Light only: dark --error falls to 3.9:1 there.
describe('light theme tints', () => {
    const tokens = readTokens('./light.css');

    it.each(TINTED_TEXT)('--%s clears 4.5:1 on its own tint over every resting surface', token => {
        for (const surface of RESTING_SURFACES) {
            expect(
                contrast(tokens[token], tint(tokens[token], 0.2, tokens[surface])),
                `--${token} on its tint over --${surface}`
            ).toBeGreaterThanOrEqual(4.5);
        }
    });
});
