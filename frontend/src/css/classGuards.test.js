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

const ICON = /material-symbols|<Icon\b|iconClass/;

// A class belongs to the element whose opening tag precedes it, so an icon sibling never exempts it.
const elementHead = (source, index) => {
    const before = source.slice(Math.max(0, index - 800), index);
    const tags = [...before.matchAll(/<[A-Za-z]/g)];
    return tags.length
        ? before.slice(tags.at(-1).index)
        : before.slice(before.lastIndexOf('\n') + 1);
};

const inIcon = (source, index) => ICON.test(elementHead(source, index));

const sources = sourceFiles(SRC).map(file => [relative(SRC, file), readFileSync(file, 'utf8')]);

const offenders = pattern =>
    sources.flatMap(([file, source]) =>
        [...source.matchAll(pattern)]
            .filter(({ index }) => !inIcon(source, index))
            .map(({ index }) => `${file}:${source.slice(0, index).split('\n').length}`)
    );

// Text sizes come from the type scale in tailwind.css; only icon glyphs keep one-off px sizes.
it('uses no one-off px text sizes outside icons', () => {
    expect(offenders(/text-\[\d+(\.\d+)?px\]/g)).toEqual([]);
});

// Dark Violet is 4.2:1 on cards: enough for an icon (3:1), not for text, which takes text-primary-hover.
it('keeps bare text-primary on icons', () => {
    expect(offenders(/(?<![\w-])text-primary(?![\w-])/g)).toEqual([]);
});

describe('the icon exemption', () => {
    const exempt = source => inIcon(source, source.indexOf('text-primary'));

    it('covers classes inside an icon element', () => {
        expect(
            exempt('<span\n  className={`material-symbols-outlined ${on ? "text-primary" : ""}`}>')
        ).toBe(true);
        expect(exempt('<Header icon="info" iconClass="text-primary" />')).toBe(true);
    });

    it('does not reach a text element after an icon sibling', () => {
        expect(
            exempt(
                '<span className="material-symbols-outlined">info</span>\n<a className="text-primary">x</a>'
            )
        ).toBe(false);
    });
});
