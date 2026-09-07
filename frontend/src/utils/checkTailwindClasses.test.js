// Regression tests for scripts/check-tailwind-classes.mjs (run via node against
// a fixture tree, since the script reads src/ and dist/assets/ from cwd).
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';

const SCRIPT = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    '../../scripts/check-tailwind-classes.mjs'
);

let dir;
afterEach(() => dir && fs.rmSync(dir, { recursive: true, force: true }));

function fixture(jsx, css) {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'twcheck-'));
    fs.mkdirSync(path.join(dir, 'src'));
    fs.mkdirSync(path.join(dir, 'dist/assets'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'src/App.jsx'), jsx);
    fs.writeFileSync(path.join(dir, 'dist/assets/app.css'), css);
}

function run() {
    try {
        execFileSync('node', [SCRIPT], { cwd: dir, encoding: 'utf8' });
        return { code: 0 };
    } catch (e) {
        return { code: e.status, out: `${e.stdout}${e.stderr}` };
    }
}

describe('check-tailwind-classes', () => {
    it('fails on a clsx object key missing from the built CSS', () => {
        fixture(
            `export const A = (on) => <div className={clsx({ 'bg-missing': on })} />;`,
            `.bg-canvas{background:#000}`
        );
        const r = run();
        expect(r.code).toBe(1);
        expect(r.out).toContain('bg-missing');
    });

    it('passes when the clsx object key is emitted', () => {
        fixture(
            `export const A = (on) => <div className={clsx({ 'bg-canvas': on })} />;`,
            `.bg-canvas{background:#000}`
        );
        expect(run().code).toBe(0);
    });

    it('still ignores class-shaped lookup keys in a *Classes variant map', () => {
        fixture(
            `const positionClasses = { 'bottom-left': 'bottom-0 left-0' };\n` +
                `export const B = (p) => <div className={positionClasses[p]} />;`,
            `.bottom-0{bottom:0}.left-0{left:0}`
        );
        expect(run().code).toBe(0);
    });
});
