// MultiQC folder upload hook for dcc.Upload.
//
// dcc.Upload (react-dropzone under the hood) ships only file basenames to the
// Python callback. For MultiQC ingestion we want the user to drop folders
// (e.g. run_01/, run_02/, ...) and have the server group by folder name. This
// script:
//   1. Adds webkitdirectory/directory/mozdirectory to the underlying <input>
//      so the file picker offers folder selection.
//   2. Intercepts the picker `change` event (capturing phase) and rewrites
//      each File so its `name` carries `file.webkitRelativePath`
//      (e.g. "run_01/multiqc_data/multiqc.parquet").
//   3. Intercepts dropped folders, walks them via webkitGetAsEntry, and
//      synthesizes a `change` event with the renamed files — bypassing
//      react-dropzone's drop handler so it sees a flat list of paths.
//
// Activation is gated by a `depictio-multiqc-folder-upload` class on the
// upload wrapper, toggled by a clientside callback in
// project_data_collections.py based on the data-type select.

// === Clientside namespace registration ===
// Registered at the top of the file (NOT inside an IIFE) so it executes
// before anything else — Dash's clientside_callback uses these helpers
// from `window.dash_clientside.depictio_multiqc`.
window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.depictio_multiqc = window.dash_clientside.depictio_multiqc || {};

// Submit button label for the unified data-collection modal.
// Drives `create-data-collection-creation-submit.children` from the mode
// store + the replace-toggle state:
//   create        -> "Create"
//   update + ON   -> "Replace all data"
//   update + OFF  -> "Append folders"
//   clear         -> "Clear data collection"
window.dash_clientside.depictio_multiqc.compute_modal_submit_label = function (mode_data, replace_checked) {
    var mode = (mode_data && mode_data.mode) || 'create';
    if (mode === 'clear') {
        return 'Clear data collection';
    }
    if (mode === 'update') {
        return replace_checked ? 'Replace all data' : 'Append folders';
    }
    return 'Create';
};

// Typed-name guard for the clear flow. Only enforced when the unified
// modal is in `clear` mode; in all other modes the server-side
// callback owns the disabled state and we return false (enabled).
//
// Inputs (in order): mode_data, typed, expected.
window.dash_clientside.depictio_multiqc.clear_dc_typed_name_guard = function (mode_data, typed, expected) {
    var mode = (mode_data && mode_data.mode) || null;
    if (mode !== 'clear') return false;
    if (typed === null || typed === undefined) return true;
    if (expected === null || expected === undefined) return true;
    return String(typed) !== String(expected);
};

(function () {
    'use strict';

    const FOLDER_MODE_CLASS = 'depictio-multiqc-folder-upload';
    const UPLOAD_ID = 'data-collection-creation-file-upload';
    const INPUT_FLAG = '_depictioInputHookApplied';
    const WRAPPER_FLAG = '_depictioWrapperHookApplied';
    const MULTIQC_PARQUET = 'multiqc.parquet';

    // dcc.Upload puts the `id` on an outer wrapper but applies its
    // `className` prop to an INNER react-dropzone div. The folder-mode
    // class lands on that inner div, not on `#data-collection-creation-
    // file-upload`. Always probe for the class within the subtree.
    function isFolderMode(wrapper) {
        if (!wrapper) return false;
        if (wrapper.classList && wrapper.classList.contains(FOLDER_MODE_CLASS)) return true;
        return !!wrapper.querySelector('.' + FOLDER_MODE_CLASS);
    }

    // Only multiqc.parquet files matter; siblings (general_stats, modules, etc.)
    // would otherwise bloat the dcc.Upload payload and can silently exhaust the
    // 500 MB total cap, leading to "only the first run made it through" symptoms
    // when a user drops a parent like test_data/ that holds many run_XX folders.
    function isMultiqcParquet(name) {
        if (!name) return false;
        const parts = String(name).replace(/\\/g, '/').split('/');
        return parts[parts.length - 1] === MULTIQC_PARQUET;
    }

    function setFolderModeAttrs(input, on) {
        if (on) {
            input.setAttribute('webkitdirectory', '');
            input.setAttribute('directory', '');
            input.setAttribute('mozdirectory', '');
        } else {
            input.removeAttribute('webkitdirectory');
            input.removeAttribute('directory');
            input.removeAttribute('mozdirectory');
        }
    }

    function installChangeListener(input) {
        if (input[INPUT_FLAG]) return;
        input[INPUT_FLAG] = true;

        // Capturing phase so we mutate input.files before react-dropzone's
        // onChange handler reads them. We filter to multiqc.parquet here so
        // the parent-folder picker (e.g. user picks test_data/) only forwards
        // the parquets to react-dropzone instead of every file in the tree.
        input.addEventListener('change', function (ev) {
            const wrapperEl = document.getElementById(UPLOAD_ID);
            const inFolderMode = isFolderMode(wrapperEl);
            const files = ev.target && ev.target.files;
            if (!files || files.length === 0) return;
            console.info('[multiqc-folder-upload] change handler — input.files.length =',
                files.length, 'folderMode =', inFolderMode);
            const dt = new DataTransfer();
            let kept = 0;
            for (const f of files) {
                const rel = f.webkitRelativePath || f.name;
                if (inFolderMode && !isMultiqcParquet(rel)) continue;
                dt.items.add(new File([f], rel, {
                    type: f.type,
                    lastModified: f.lastModified,
                }));
                kept += 1;
            }
            console.info('[multiqc-folder-upload] change handler — kept', kept, 'of', files.length,
                '— filenames:', Array.from(dt.files).map(function (f) { return f.name; }));
            if (kept !== files.length) {
                try {
                    ev.target.files = dt.files;
                } catch (e) {
                    console.warn('[multiqc-folder-upload] could not rewrite files:', e);
                }
            }
        }, true);
    }

    function readAllEntries(dirEntry) {
        return new Promise(function (resolve, reject) {
            const reader = dirEntry.createReader();
            const all = [];
            const readBatch = function () {
                reader.readEntries(function (batch) {
                    if (!batch || batch.length === 0) {
                        resolve(all);
                    } else {
                        for (const e of batch) all.push(e);
                        readBatch();
                    }
                }, reject);
            };
            readBatch();
        });
    }

    async function walkEntry(entry, prefix, out) {
        if (entry.isFile) {
            // Skip siblings of multiqc.parquet at walk time so we never
            // even read their bytes — this is what makes a deep `test_data/`
            // drop with N runs stay at N files instead of thousands.
            if (entry.name !== MULTIQC_PARQUET) return;
            await new Promise(function (resolve, reject) {
                entry.file(function (file) {
                    const renamed = new File([file], prefix + entry.name, {
                        type: file.type,
                        lastModified: file.lastModified,
                    });
                    out.push(renamed);
                    resolve();
                }, reject);
            });
        } else if (entry.isDirectory) {
            const subs = await readAllEntries(entry);
            for (const sub of subs) {
                await walkEntry(sub, prefix + entry.name + '/', out);
            }
        }
    }

    async function handleFolderDrop(entries, input) {
        if (!entries || entries.length === 0) return false;
        console.info('[multiqc-folder-upload] drop — entries =', entries.length,
            'names =', entries.map(function (e) { return e.name; }));

        const collected = [];
        await Promise.all(entries.map(function (e) {
            return walkEntry(e, '', collected);
        }));
        console.info('[multiqc-folder-upload] walk done — collected', collected.length,
            'parquets:', collected.map(function (f) { return f.name; }));
        if (collected.length === 0) {
            console.warn('[multiqc-folder-upload] no multiqc.parquet found in dropped folder(s)');
            return false;
        }

        const dt = new DataTransfer();
        for (const f of collected) dt.items.add(f);
        try {
            input.files = dt.files;
            console.info('[multiqc-folder-upload] input.files.length after assignment =',
                input.files.length);
            input.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        } catch (e) {
            console.warn('[multiqc-folder-upload] could not synthesize change:', e);
            return false;
        }
    }

    function installWrapperListener(wrapper) {
        if (wrapper[WRAPPER_FLAG]) return;
        wrapper[WRAPPER_FLAG] = true;

        wrapper.addEventListener('drop', function (ev) {
            if (!isFolderMode(wrapper)) return;
            const items = ev.dataTransfer && ev.dataTransfer.items;
            if (!items || items.length === 0) return;

            // Snapshot the DataTransferItemList into a plain array up-front.
            // The list is live and tied to the event lifetime — once we've
            // started any async work it can shrink to 0. We also call
            // webkitGetAsEntry() exactly once per item: a second call on
            // the same DataTransferItem returns null in Chrome/Edge, which
            // is what caused only the first run_XX folder to ever survive.
            const itemsLen = items.length;
            console.info('[multiqc-folder-upload] drop fired — items.length =', itemsLen);
            const entries = [];
            let hasDirectory = false;
            for (let i = 0; i < itemsLen; i++) {
                const it = items[i];
                if (!it || typeof it.webkitGetAsEntry !== 'function') continue;
                const entry = it.webkitGetAsEntry();
                if (!entry) continue;
                entries.push(entry);
                if (entry.isDirectory) hasDirectory = true;
            }
            console.info('[multiqc-folder-upload] captured', entries.length, 'entries —',
                entries.map(function (e) {
                    return (e.isDirectory ? 'DIR ' : 'FILE ') + e.name;
                }));

            // Only hijack the drop if at least one entry is a directory;
            // bare files in MultiQC mode flow through react-dropzone as-is.
            if (!hasDirectory) return;

            ev.preventDefault();
            ev.stopPropagation();

            const input = wrapper.querySelector('input[type="file"]');
            if (!input) return;
            handleFolderDrop(entries, input);
        }, true);
    }

    function refresh() {
        const wrapper = document.getElementById(UPLOAD_ID);
        if (!wrapper) return;
        const input = wrapper.querySelector('input[type="file"]');
        const folderMode = isFolderMode(wrapper);
        if (input) {
            setFolderModeAttrs(input, folderMode);
            installChangeListener(input);
        }
        installWrapperListener(wrapper);
    }

    document.addEventListener('DOMContentLoaded', refresh);
    new MutationObserver(refresh).observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['class'],
    });
})();
