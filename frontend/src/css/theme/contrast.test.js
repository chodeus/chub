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
];
const SOLID_FILLS = ['success', 'warning', 'info', 'error', 'accent'];
const RESTING_SURFACES = ['bg', 'surface', 'surface-alt'];

// Theme block only: the prefers-contrast override further down redefines some tokens.
const readTokens = file => {
    const css = readFileSync(new URL(file, import.meta.url), 'utf8');
    const block = css.slice(0, css.indexOf('@media'));
    return Object.fromEntries(
        [...block.matchAll(/--([\w-]+):\s*(#[0-9a-f]{3,6})\b/gi)].map(([, name, hex]) => [
            name,
            hex,
        ])
    );
};

const luminance = hex => {
    const digits = hex.length === 4 ? [...hex.slice(1)].map(d => d + d) : hex.slice(1).match(/../g);
    const [r, g, b] = digits.map(d => {
        const c = parseInt(d, 16) / 255;
        return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

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
