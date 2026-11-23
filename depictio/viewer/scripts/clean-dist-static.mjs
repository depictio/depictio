#!/usr/bin/env node
/**
 * Empty `dist-static/` before `build:static` writes it: the runtime
 * (`vite.combined.config.ts`), the JBrowse add-on build and the add-ons all
 * write into it without clearing it, so a leftover from an older build (the
 * template `static.html` shipped before the runtime was built once) would
 * otherwise stay.
 */
import { rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const VIEWER_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
rmSync(join(VIEWER_DIR, 'dist-static'), { recursive: true, force: true });
