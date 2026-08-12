#!/usr/bin/env node
// Fails when a class used in src/ is missing from the built CSS — Tailwind
// silently drops unresolvable candidates. Run after `npm run build` (reads dist/).
import fs from 'node:fs';
import path from 'node:path';

const SRC = 'src';
const DIST = 'dist/assets';

/** Classes deliberately absent from the Tailwind build (each needs a reason). */
const ALLOWLIST = new Set([
    // Google's Material Symbols webfont ships this one; base.css only sizes it.
    'material-symbols-outlined',
]);

/** Every .js/.jsx file Tailwind scans (mirrors @source in src/css/tailwind.css). */
function sourceFiles(dir) {
    const out = [];
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, e.name);
        if (e.isDirectory()) out.push(...sourceFiles(p));
        else if (/\.(js|jsx)$/.test(p)) out.push(p);
    }
    return out;
}

/** Class selectors from the built CSS, with CSS escapes (\: \/ \[) removed. */
function emittedClasses() {
    const files = fs.existsSync(DIST) ? fs.readdirSync(DIST).filter(f => f.endsWith('.css')) : [];
    if (files.length === 0) {
        console.error(`check:classes — no CSS in ${DIST}. Run \`npm run build\` first.`);
        process.exit(2);
    }
    const set = new Set();
    for (const f of files) {
        const css = fs.readFileSync(path.join(DIST, f), 'utf8');
        for (const m of css.matchAll(/\.((?:\\[^\s]|[a-zA-Z0-9_-])+)/g)) {
            set.add(m[1].replace(/\\(.)/g, '$1'));
        }
    }
    return set;
}

/** Slice the expression after a `className=` / `…Classes =` match, so only
 * strings that really hold classes are scanned (not class-shaped prop enums). */
function sliceRegion(text, start) {
    const open = { '{': '}', '[': ']' };
    const c = text[start];
    if (c === "'" || c === '"' || c === '`') {
        for (let i = start + 1; i < text.length; i++) {
            if (text[i] === '\\') i++;
            else if (text[i] === c) return text.slice(start, i + 1);
        }
        return text.slice(start);
    }
    if (!open[c]) return '';
    const stack = [c];
    let i = start + 1;
    while (i < text.length && stack.length) {
        const ch = text[i];
        const top = stack[stack.length - 1];
        if (top === "'" || top === '"') {
            if (ch === '\\') i++;
            else if (ch === top) stack.pop();
        } else if (top === '`') {
            if (ch === '\\') i++;
            else if (ch === '`') stack.pop();
            else if (ch === '$' && text[i + 1] === '{') {
                stack.push('{');
                i++;
            }
        } else if (ch === '/' && text[i + 1] === '/') {
            i = text.indexOf('\n', i);
            if (i < 0) break;
        } else if (ch === '/' && text[i + 1] === '*') {
            i = text.indexOf('*/', i) + 1;
            if (i < 1) break;
        } else if (ch === "'" || ch === '"' || ch === '`' || open[ch]) {
            stack.push(ch);
        } else if (ch === '}' || ch === ']') {
            stack.pop();
        }
        i++;
    }
    return text.slice(start, i);
}

const REGION_START = /(?:className|\b[A-Za-z_$][\w$]*(?:Class|Classes|ClassName))\s*[=:]\s*/g;
const TOKEN = /^[a-zA-Z][a-zA-Z0-9_:/.%[\]-]*$/;

/** Class tokens in one file; template-literal fragments touching a `${}` are
 * dropped (`log-block--${lvl}` yields `log-block--`, not a class). */
function usedClasses(text) {
    const out = new Set();
    const strings =
        /'([^'\\\n]*(?:\\.[^'\\\n]*)*)'|"([^"\\\n]*(?:\\.[^"\\\n]*)*)"|`([^`\\]*(?:\\.[^`\\]*)*)`/gs;
    for (const start of text.matchAll(REGION_START)) {
        const region = sliceRegion(text, start.index + start[0].length);
        for (const m of region.matchAll(strings)) {
            // Prettier leaves no space before an object key's colon, so this
            // skips the lookup keys of a variant->classes map, not a ternary.
            if (region[m.index + m[0].length] === ':') continue;
            const chunks = (m[1] ?? m[2] ?? m[3]).split(/\$\{[^}]*\}/s);
            chunks.forEach((chunk, i) => {
                const parts = chunk.split(/\s+/).filter(Boolean);
                // A token glued to an interpolation is a fragment, not a class:
                // `log-block--${lvl}` yields `log-block--`.
                if (i > 0 && !/^\s/.test(chunk)) parts.shift();
                if (i < chunks.length - 1 && !/\s$/.test(chunk)) parts.pop();
                for (const p of parts) if (TOKEN.test(p)) out.add(p);
            });
        }
    }
    return out;
}

/** True when the class shares a `-` prefix with an emitted one — a live-family
 * utility (`bg-canvas`), not a bespoke component class (`item-counter`). */
function inLiveFamily(cls, prefixes) {
    const bits = cls.split(':').pop().split('-');
    for (let i = bits.length - 1; i > 0; i--) {
        if (prefixes.has(bits.slice(0, i).join('-') + '-')) return true;
    }
    return false;
}

const emitted = emittedClasses();
const prefixes = new Set();
for (const cls of emitted) {
    const bits = cls.split(':').pop().split('-');
    for (let i = 1; i < bits.length; i++) prefixes.add(bits.slice(0, i).join('-') + '-');
}

const missing = new Map();
for (const file of sourceFiles(SRC)) {
    for (const token of usedClasses(fs.readFileSync(file, 'utf8'))) {
        if (emitted.has(token) || ALLOWLIST.has(token)) continue;
        if (!token.includes('-') || !inLiveFamily(token, prefixes)) continue;
        if (!missing.has(token)) missing.set(token, new Set());
        missing.get(token).add(file);
    }
}

if (missing.size === 0) {
    console.log(`check:classes — OK (${emitted.size} classes emitted).`);
    process.exit(0);
}
console.error(`check:classes — ${missing.size} class(es) used in ${SRC}/ but not emitted:\n`);
for (const [cls, files] of [...missing].sort()) {
    console.error(`  ${cls}\n      ${[...files].join('\n      ')}`);
}
console.error('\nDefine the token/utility in src/css/tailwind.css, or use the intended class.');
process.exit(1);
