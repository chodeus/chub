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

// Text sizes come from the type scale in tailwind.css; only icon glyphs keep one-off px sizes.
it('uses no one-off px text sizes outside icons', () => {
    const offenders = sourceFiles(SRC).flatMap(file =>
        readFileSync(file, 'utf8')
            .split('\n')
            .flatMap((line, i) =>
                /text-\[\d+(\.\d+)?px\]/.test(line) && !/material-symbols|<Icon\b/.test(line)
                    ? [`${relative(SRC, file)}:${i + 1}`]
                    : []
            )
    );
    expect(offenders).toEqual([]);
});
