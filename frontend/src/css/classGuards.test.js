import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

// Not new URL('..', import.meta.url): Vite rewrites that literal form into a served http: URL.
const SRC = join(process.cwd(), 'src');

const sourceFiles = dir =>
    readdirSync(dir).flatMap(name => {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) return sourceFiles(path);
        return /\.jsx?$/.test(name) && !name.includes('.test.') ? [path] : [];
    });

// An icon's classes sit on, or just below, the line that names the glyph.
const ICON = /material-symbols|<Icon\b|iconClass/;

const sourceLines = sourceFiles(SRC).flatMap(file =>
    readFileSync(file, 'utf8')
        .split('\n')
        .map((text, i, lines) => ({
            at: `${relative(SRC, file)}:${i + 1}`,
            text,
            lead: lines.slice(Math.max(0, i - 2), i + 1).join('\n'),
        }))
);

// Text sizes come from the type scale in tailwind.css; only icon glyphs keep one-off px sizes.
it('uses no one-off px text sizes outside icons', () => {
    const offenders = sourceLines.filter(
        ({ text }) => /text-\[\d+(\.\d+)?px\]/.test(text) && !ICON.test(text)
    );
    expect(offenders.map(({ at }) => at)).toEqual([]);
});

// Dark Violet is 4.2:1 on cards: enough for an icon (3:1), not for text, which takes text-primary-hover.
it('keeps bare text-primary on icons', () => {
    const offenders = sourceLines.filter(
        ({ text, lead }) => /(^|[^\w-])text-primary(?![\w-])/.test(text) && !ICON.test(lead)
    );
    expect(offenders.map(({ at }) => at)).toEqual([]);
});
