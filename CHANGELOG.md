# Changelog

### Docker Images 🐳

```plaintext
ghcr.io/depictio/depictio:1.22.0
ghcr.io/depictio/depictio:latest
ghcr.io/depictio/depictio:stable
ghcr.io/depictio/depictio:edge
```


<details>
<summary>Click to expand the changelog for 1.22.0</summary>

### Changes 📜

#### Other Changes 📝

* Bump version: 1.21.0 → 1.22.0 [6a1da2d4c]
* fix(cli): `depictio template check --run` finds a YAML/JSON samplesheet [fd0645802]
* Revert "ci(images): publish each PR's all-in-one image" [085f27caf]
* ci(images): publish each PR's all-in-one image, to try the module before a release [cf8c8171b]
* fix(eager 2.5.3): the Genotype step cites its collection [a3b028232]
* feat(cli): read a YAML/JSON samplesheet exactly as the same CSV [4905f13f1]
* fix(recipes): name a missing samplesheet field a key in a YAML/JSON sheet [b6028c8c6]
* chore(ampliseq 3.1.0): template version 3.0.0 for the samplesheet column [e96287f7d]
* fix(rnaseq): pct_trimmed from MultiQC's trim_galore data [78e077dc1]
* docs(files): diagram of the presigned and proxy modes for indexed files [28cb8f8fe]
* perf(recipes): write a recipe's table a batch at a time [db48b418b]
* fix(nfcore_drift): a lost output column is an error while the template names it [87e0bdb22]
* fix(ampliseq 3.1.0): the samplesheet's sample id is `sample` [c8435eaff]
* fix(cli): read a sheet column of mixed YAML types as text [cd746a702]
* test(delta): compare a partitioned table read back in the frame's column order [82ef86555]
* fix(files): stream indexed files through the API when S3 is internal [837b5512b]
* perf(hmmer): hold hmm_profile's text columns as Categorical [6a0aed807]
* feat(helm): let backend and worker pods reach the internet on Serve [90f0c2f00]
* chore(catalog): refresh the hmmer lock for its unreleased 1.1.0 [d22cc73ba]
* fix(delta): hand deltalake the frame a slice at a time ([#1418](https://github.com/depictio/depictio/pull/1418)) [bc8600286]
* fix(runs): say when the shared-samples check read only some reports ([#1400](https://github.com/depictio/depictio/pull/1400)) [913e9955b]
* fix(hmmer): read family alignments and models one file at a time ([#1418](https://github.com/depictio/depictio/pull/1418)) [53365fab5]
* fix(runs): two workflows sharing a run tag keep their files apart ([#1401](https://github.com/depictio/depictio/pull/1401)) [7326b3bd6]
* feat(viewer): onboarding coach, landing news and Guide parts for Metadata and What's new [a62e285f6]
* fix(migrate): say where a target redirects instead of "not JSON" [be5b0c169]
* fix(map): read GeoJSON collections with the shared S3 client [3077883c1]
* fix(migrate): carry indexed_file objects in project bundles [4a47a272c]
* fix(seed): genome tracks showcase is opt-in [14d2148ad]
* Update CHANGELOG.md for v1.21.0 [7563e47ed]
* feat(nfcore): compare a version a pull request adds with its predecessor [9eeb414fd]
* feat(nfcore): deterministic drift detection between two releases' runs [5975cc54e]
* chore(templates): refresh the lock after formatting [c3fafa0d5]
* feat(templates): nf-core quantms 1.2.0 [838aa3a23]
* docs(eager 2.5.3): the pinned megatest is the 2.4.5 run [aaaeb62b5]
* feat(templates): nf-core eager 2.5.3 [301319efb]
* feat(templates): nf-core rnasplice 2.0.0 [522c2770b]
* feat(templates): nf-core proteinfamilies 2.6.0 [d18630ffc]
* feat(templates): nf-core ampliseq 3.1.0 [e40688d24]
* feat(templates): nf-core mhcquant 3.3.0, variantbenchmarking 1.6.1, rnaseq 3.28.0, sarek 3.12.0 [438669d8b]
* feat(templates): what a new pipeline release changes for the rules [b27aebd25]
* docs(nextflow): exact commands and params in the flow schema [e6311dd8b]
* feat(cli): depictio template check, and a doc for pipeline developers [7e6d63fcf]
* docs(templates): illustrated from_params schema with the rnaseq example and CI [5eced692e]
* docs(nextflow): illustrated schemas with logos, and the shared-node schema [3b063c117]
* refactor(nextflow): simplify after review [3801291aa]
* docs(templates): schema counts after the review [2cda6f447]
* fix(templates): review of from_params rules [815d00190]
* fix(nextflow): publish runs that skipped their report, skip old artifacts, quote paths [1ec0cf85a]
* docs(templates): from_params rules, with a hand-drawn schema [b56d5a2fb]
* docs(nextflow): hand-drawn schemas of the module's flow and of what CI runs [04864d2d4]
* ci(allinone): run viralrecon without pangolin's GitHub-API database update [35f75e8b2]
* ci(allinone): retry an nf-core release that the strict parser rejects with the old one [2940a025b]
* ci(allinone): drop scrnaseq from the template matrix [757fa4590]
* ci(allinone): run the nf-core pipelines with Nextflow's default parser [d97dbadf5]
* refactor(nextflow): depictio/publish takes its settings as inputs, not params [4d1890431]
* ci(allinone): clone nf-core pipelines with git, not through GitHub's API [abe1fe8b2]
* feat(nextflow): depictio/publish subworkflow, one integration for every pipeline [bd9b15fd3]
* feat(templates): derive route variables from the run's params.json, per template [8f0fee899]
* ci(allinone): Apptainer, cli_config and eight more nf-core templates [9425670b7]
* ci(allinone): run a real nf-core/rnaseq through the module in the image [e22b72568]
* ci(allinone): override the module's container with withName, not process.container [70adff885]
* feat(nextflow): run the depictio/ingest module in the all-in-one image [b499f33e5]
* fix(cli): keep CSV reads of JSON reports that recipes and DCs declare [a8d381cc2]
* feat(cli): accept YAML and JSON samplesheets [37811b76f]


</details>

### Documentation 📖

For more details, please refer to the [documentation](https://depictio.github.io/depictio-docs/)

### Docker Images 🐳

```plaintext
ghcr.io/depictio/depictio:1.21.0
ghcr.io/depictio/depictio:latest
ghcr.io/depictio/depictio:stable
ghcr.io/depictio/depictio:edge
```


<details>
<summary>Click to expand the changelog for 1.21.0</summary>

### Changes 📜

#### Improvements 🚀

* style: sort imports for ruff 0.16.1 [cff4254c2]
* style: format the overall split test for the CI ruff [aea962df4]

#### Documentation Updates 📚

* docs: multi-run templates, recipe scopes and per-run changes [0e3926f87]
* docs: screenshots of the What's new key and the change lists [4f7b48e4d]
* docs: screenshots of changed since your last visit [8d4d4cc40]
* docs: changed since your last visit, and its switches in Helm and local [a33eef5ee]

#### Other Changes 📝

* Bump version: 1.21.0-b6 → 1.21.0 [6cac2a094]
* feat(changes): split into All, each new run and Seen before [faafb6a24]
* test(e2e): the preview and editor check watches mark writes, not reads [fea0c8c8b]
* feat(changes): Before | Now says it draws standard figures only [746806565]
* fix(changes): split MultiQC runs with more than 200 sample names [cd6c31946]
* feat(advanced-viz): complex heatmap group strip and split by run [e36e85fc4]
* feat(editor): What's new and the run views in the editor [d38176f3f]
* feat(changes): a run takes its group's colour, in What's new, the Overlay and the toasts [b98d2103b]
* fix(viewer): header button tooltips above popovers [f7f60b463]
* ci(allinone): prove the image on arm64 and that a reopen keeps the data [62d580571]
* ci(images): publish the all-in-one image to GHCR on releases [062850ff1]
* feat(viewer): What's new by run, and the run Overlay on every visualisation [63fd1fec1]
* fix(api): drop a pending compute entry past its task's time limit [8a925250e]
* feat(api): per-run changes, run lineage and run groups for advanced viz [387244dd6]
* feat(ingest): attach writes only its run, recipes that mix samples recompute over every run [69e761d00]
* feat(ingest): run recipes and single files per run, keep template values per run [8b37616a4]
* test(ingest): a black-box harness for multi-run template ingestion [f2c92bd63]
* fix(viewer): honest new-rows counts, failed marks, stale legend [b8195b140]
* feat(projects): Map coordinates only where coordinates are; clearer way back [c5ea30bdd]
* feat(projects): clear a run's marking from the Data table [b1f2c8acc]
* feat(projects): a run's rows in the collection's own Data table [3d17d5e28]
* feat(viewer): new rows on top, the rows seen faded below [d7908b13f]
* feat(viewer): show the rows a new run added [4d85dff84]
* fix(viewer): no Plotly title inside a split panel [8ffd4e520]
* feat(viewer): overlay tables by run, quiet the per-figure chip [b7ecfebc3]
* feat(viewer): mark notifications as seen, one by one or all [b2d282ea3]
* feat(viewer): hide what was seen, and overlay the General Stats table [2cf76e2a3]
* feat(changes): split MultiQC figures on their new samples [5bcad8d01]
* fix(changes): MultiQC overlay keeps the new samples' own colours [b261e942d]
* fix(changes): content digest ignores the write time and float noise [c66a8c604]
* feat(changes): a commit that rewrites identical rows is not news [dde28e698]
* feat(changes): split code-mode figures per side in the what's new view [2889a2d51]
* feat(changes): Off | Overlay | Split view of what is new [b3d6466e0]
* feat(changes): highlight what is new on every figure at once [3dbf8cbd5]
* feat(versions): History marks the version you last viewed [f6d863314]
* fix(changes): only a mark that moves closes the autosave window [5210c151d]
* feat(projects): Activity history in the What's new look [35f518a58]
* feat(projects): shorter tab subtitles, so four tabs read in full [ef76fdb2c]
* fix(changes): count a collection's rows by its totals [198f286c2]
* feat(projects): one Activity tab for the ingestion report and the timeline [201101fc0]
* test(e2e): open the filter-propagation dashboard through the card's link [0b20a3c22]
* fix(multiqc): an append validates only the reports that replace the old set [bb67a5c27]
* test(e2e): a preview and the editor make no call about the dashboard's mark [93c12b39b]
* fix(versions): a reader's mark closes the autosave window it points at [91341618a]
* feat(viewer): What's new as a header key, and one look for every change list [8f1d5ea7b]
* fix(api): a new run's registration time in UTC in the changes views [a1f0cc7f4]
* fix(changes): group once when x and colour share a column; overwrite row totals [8f272daa3]
* fix(projects): call the version link of a run "Layout before <run>" [202cd9085]
* fix(viewer): Before | Now draws the reports the reader saw, and the dot sits clear of content [edbaba64f]
* fix(api): show ingestion times in UTC in the changes views [f0bdcb7cc]
* test(e2e): changed since your last visit [4077f3916]
* feat(viewer): changed since your last visit, updated marks and figure before/after [a6a1662d0]
* feat(chrome): the notifications bell in the glass shell [96fc3b84a]
* fix(api): an ingestion is news even to the reader who ran it [f2976c878]
* feat(projects): new runs, what a run produced, and a project timeline [d522fd6dd]
* feat(notifications): a bell and a live toast when an ingestion finishes [2d68d16be]
* fix(api): MultiQC changes survive an append that recreates every report [9b3d9bd95]
* feat(api): which points, bars and samples of a figure changed [3c41872f6]
* feat(api): what changed since a reader's last visit [3cf34cfdb]
* feat(versions): MultiQC data time travel by report set [1afb3e5c0]
* fix(ingest): record which ingestion and which run wrote the data [58abbe925]
* feat(runs): a Runs tab that says what each scan found and changed [e542fcebc]
* feat(refresh): read again only what changed, with a switch to force it [1e667e090]
* feat(attach-run): hold back a run whose reports name samples already in the project [a335e2c5a]
* feat(project-builder): define collections yourself, on a server or without one [2c9c3fa75]
* feat(chrome): one server footer for the landing pages and the dashboard sidebar [7c4a7ce37]
* Update CHANGELOG.md for v1.21.0-b6 [353f9410b]


</details>

### Documentation 📖

For more details, please refer to the [documentation](https://depictio.github.io/depictio-docs/)

### Docker Images 🐳

```plaintext
ghcr.io/depictio/depictio:1.21.0-b6
ghcr.io/depictio/depictio:latest
ghcr.io/depictio/depictio:stable
ghcr.io/depictio/depictio:edge
```


<details>
<summary>Click to expand the changelog for 1.21.0-b6</summary>

### Changes 📜

#### Other Changes 📝

* Bump version: 1.21.0-b5 → 1.21.0-b6 [6e70081bc]
* test(links): the hop-composition fake accepts text_match [ddd52f0e4]
* fix(nf-core/crisprseq): Guide comparison section uses a bundled icon (template 2.2.5) [3be82eb51]
* fix(nf-core/crisprseq): placeholders show the pipe as the regex alternation (template 2.2.4) [5ee72dc84]
* feat(nf-core/crisprseq): guide comparison tabs, edit quartiles, replicate agreement, indel size matrix [e06f055dd]
* test(sarek): the mapping-only tests read the latest template (3.11.0) [88f9509a3]
* fix(figure): hover template keeps its extra tail, translucent colours keep the neutral label [588fade01]
* feat(sarek): genome browser in Explore, annotated burden heatmap, tooltips in series colours [7d62646f0]
* feat(viewer): contigs in karyotype order for mosdepth, overflow cue on the sidebar tab list [6a6909113]
* test(publish-lock): classify the text filter and group resolution routes [723380320]
* test(links): the reverse resolve passes text_match to the translation [69bc4532a]
* docs(interactive): TextInput placeholder example uses the pipe of a regular expression [f70179dd3]
* feat(interactive): TextInput match list follows the typing, marks each alternative in its own colour [407cce42b]
* feat(interactive): TextInput regex filter, multi-value always_selected, group translation for advanced viz [a24785a36]
* fix(projects): the push host reads the server-info store for admins only [8a5ff691f]
* feat(projects): a clickable toast for received projects, on every page [c5592092c]
* feat(helm): turn on realtime events for the EMBL instances [2d162e5ab]
* feat(projects): show a received project at once, with a toast [74b2ae6b5]
* feat(migration): push a received project to admin browsers as it arrives [414a96815]
* fix(projects): align the received-projects banner with the page palette [9f2e1ccc6]
* fix(helm): allow the EMBL instances as send targets from the UI [c1aea3957]
* Update CHANGELOG.md for v1.21.0-b5 [ad389453e]


</details>

### Documentation 📖

For more details, please refer to the [documentation](https://depictio.github.io/depictio-docs/)

### Docker Images 🐳

```plaintext
ghcr.io/depictio/depictio:1.21.0-b5
ghcr.io/depictio/depictio:latest
ghcr.io/depictio/depictio:stable
ghcr.io/depictio/depictio:edge
```


<details>
<summary>Click to expand the changelog for 1.21.0-b5</summary>

### Changes 📜

#### Other Changes 📝

* Bump version: 1.21.0-b4 → 1.21.0-b5 [b2ad4421e]
* feat(admin): disable Add user in single-user and public mode [c8a89a9e3]
* feat(admin): multi-select with bulk delete and a compact one-line mode [430c9f0b1]
* feat(admin): row actions in the admin Projects and Dashboards tables [4b29b901b]
* feat(admin): admin tables, activity view for project members, UI fixes [23383cfc1]
* Update CHANGELOG.md for v1.21.0-b4 [fd060acd7]
* feat(tables): mark the lat/lon columns of a table from its page and from Add data [86ef861b5]


</details>

### Documentation 📖

For more details, please refer to the [documentation](https://depictio.github.io/depictio-docs/)

### Docker Images 🐳

```plaintext
ghcr.io/depictio/depictio:1.21.0-b4
ghcr.io/depictio/depictio:latest
ghcr.io/depictio/depictio:stable
ghcr.io/depictio/depictio:edge
```


<details>
<summary>Click to expand the changelog for 1.21.0-b4</summary>

### Changes 📜

#### Improvements 🚀

* style: ruff format the public-mode import tests [538188c04]

#### Other Changes 📝

* Bump version: 1.21.0-b3 → 1.21.0-b4 [c4827ab1e]
* feat(api): let admins and project editors import dashboards in public mode ([#1335](https://github.com/depictio/depictio/pull/1335)) [a8595dddd]
* feat(migration): let every chart-deployed instance publish to any public https host [0ef6dd3dd]
* Update CHANGELOG.md for v1.21.0-b3 [b39a3c202]


</details>

### Documentation 📖

For more details, please refer to the [documentation](https://depictio.github.io/depictio-docs/)

### Docker Images 🐳

```plaintext
ghcr.io/depictio/depictio:1.21.0-b3
ghcr.io/depictio/depictio:latest
ghcr.io/depictio/depictio:stable
ghcr.io/depictio/depictio:edge
```


<details>
<summary>Click to expand the changelog for 1.21.0-b3</summary>

### Changes 📜

#### New Features ✨

* feat: restore a past version of an edited table, as a new version; a one-line edit lock [c4ba03486]
* feat: lock cell edits per table, unlocked to keep it as metadata [9106d196f]
* feat: add one table from its URL, previewed by the server; drop the create dialog [a936fb2e8]
* feat: one Add data flow, and tables edited and updated from a file [2c1789a1f]

#### Improvements 🚀

* style: sort the imports of the data collection routes [499cfab64]
* style: ruff format the table edit tests [3201eee7c]

#### Chores 🧹

* chore: restore the default dashboard thumbnails [756aee4fd]

#### Documentation Updates 📚

* docs: settle the open points of the annotations design and add its plan [9d35e3431]
* docs: design for session annotations on dashboards [29c566f7d]

#### Other Changes 📝

* Bump version: 1.21.0-b2 → 1.21.0-b3 [a2377bd04]
* test(publish): penguins_publish project and Helm overlays for a two-instance publish test [b7d439cb1]
* fix(publish): bundle a dashboard logo under the dashboard_id it is stored by [ad571f9b3]
* test(e2e): open the labels panel on the first eligible table in every test [896593202]
* test(e2e): start the per-table label test on the first table [991b23c3f]
* test(e2e): show sheets[0] before keying a file or a merge on it [1f5bd8f01]
* test(e2e): select a cell's text with the platform's select-all key [03c5d94bd]
* test(e2e): read a session-label row key where the unpinned key column is [3dcfc8699]
* test(e2e): session labels call the API by its same-origin path from the page [3d970f6da]
* test(annotations): check the label cap against the group name cap in the API tests [13135fcc3]
* fix(annotations): a table without its key column is no longer offered for labelling [fa43602a0]
* feat(viewer): Add data opens with the same header as New project [d182e9352]
* test(e2e): drop Add data routes still in flight when the test ends [f872af450]
* test(e2e): check the Add data dialog is gone, not the empty modal root Mantine keeps [8397b68fd]
* feat(viewer): name the two sides of Add data Upload and Read in place [b9c34a29b]
* fix(viewer): a storage that does not answer no longer blocks Next; e2e follows the new folder wording [12b10e2c5]
* feat(viewer): label columns say where they live (this browser, your account, shared) [f7bded487]
* feat(viewer): a folder with no pipeline says what it holds; the example is ampliseq [e5efdd761]
* feat(viewer): Analysis, Metadata, Comments and Search fill the screen on a phone [fecf9f9c9]
* fix(viewer): the Analysis and Metadata panels stay open on a phone [8146a0100]
* fix(viewer): the editor's dock no longer runs under the notes button beside an open panel [76b87d7f6]
* fix(viewer): Metadata panel actions grouped by what they act on [3997f393d]
* fix(viewer): Metadata panel icon buttons in the panel's own button style [30d3b35d2]
* fix(viewer): Metadata panel actions as compact icons beside the table choice [635a5f131]
* fix(viewer): Metadata panel without the other-tables list, grip kept inside the card [ef911fe71]
* fix(viewer): right panels below the modals, dock and notes button clear of them, Metadata button sooner [6b995f58f]
* feat(viewer): Metadata panel links to the table's page in the project [69458b3aa]
* feat(viewer): split panels, Metadata in the editor, copy/paste and undo in the grid [2ac977d59]
* fix(split): a label's key column finds its column in a collection that spells it differently [78ef80afc]
* Share session labels on a dashboard and export them as a metadata sheet [9a1fb39b0]
* feat(annotations): label only metadata tables linked to the data, in a Metadata panel [c16767777]
* feat(viewer): labels as a tab of the Analysis panel, edited in one grid [4f40842a7]
* feat(viewer): annotate from a file with the table editor's three modes [b80cad51d]
* feat(viewer): annotations from a dropped file stay in the browser [1ccc59072]
* fix(viewer): give the Annotate header button its own test id [b3765bbf1]
* test(e2e): session annotations from labels to groups, drop, save to table [4e65cc396]
* feat(viewer): Annotate panel labels samples and feeds the Analysis groups [46f6b7305]
* feat(react-core): derive selection groups from session annotations [742fb455e]
* feat(api): session annotations go with their dashboard, project or user [e7084ef27]
* feat(api): per-user session annotations on a dashboard [50d9d5981]
* feat(models): session annotations a viewer keeps on a dashboard [3ce3cdb64]
* feat(api): let one table preview return up to 10,000 rows [02cb8fa7b]
* feat(viewer): project Runs tab, reworked collection viewer and derived lineage [58648c592]
* Update CHANGELOG.md for v1.21.0-b2 [6cd45e6a8]


</details>

### Documentation 📖

For more details, please refer to the [documentation](https://depictio.github.io/depictio-docs/)

### Docker Images 🐳

```plaintext
ghcr.io/depictio/depictio:1.21.0-b2
ghcr.io/depictio/depictio:latest
ghcr.io/depictio/depictio:stable
ghcr.io/depictio/depictio:edge
```


<details>
<summary>Click to expand the changelog for 1.21.0-b2</summary>

### Changes 📜

#### Other Changes 📝

* Bump version: 1.21.0-b1 → 1.21.0-b2 [7907ad6b1]
* feat(viewer): add tables from a folder, or another run, from the project page [a751538e3]
* feat(viewer): start a project from the data, the pipeline as an optional correction [29897dbe5]
* fix(viewer): a layout of several runs is a real workflow whatever its engine [44c0c8b9a]
* feat(viewer): say what a project holds in its header, drop Basic/Advanced [9ad870227]
* fix(api): no duplicate tables from a folder, an empty MultiQC collection is skipped, new projects are private, a configured bucket without server credentials says so [a895b31cc]
* feat(api): record where a data collection's data came from, add tables from a folder, attach a run [578e8394f]
* fix(ci): stop tracking two node_modules symlinks that broke pnpm install [ab50098e7]
* feat(viewer): export a project as a ZIP from its settings, and an even row hover [5861bc504]
* test(e2e): open the create dialog sources through their cards [efc9f4cc2]
* fix(viewer): Send dialog says so when the project has no data files [dbd4b503a]
* fix(viewer): clearer Send dialog (steps, icons, one blocked message) and calmer projects table hover [ed98d3837]
* fix(viewer): one type scale for fields in the create project and create dashboard dialogs [b7e1f3b51]
* fix(viewer): wider New project dialog, flat dialog tabs, no double top line on buttons, back from run folder and manifest [4577712e2]
* feat(viewer): start a project from a source, no basic/advanced choice [196c0d178]
* feat(viewer): one Import dialog for another instance or a ZIP file [33830d57a]
* fix(viewer): Send opens above the settings dialog, lock switch in Send, consistent section buttons [74ff003f0]
* fix(viewer): dashboard icons on the project page, readable Send section, accent on settings tabs [9c78c50ab]
* feat(publish): Send / Receive wording, Send lives in the project settings, folded Receive options [174529b42]
* fix(publish): banner buttons in the banner colour, fixed footer and scroll hint in the request sheet [bc2d66e9c]
* feat(publish): richer migration request sheet, Projects banner, manual thumbnails [c5901dd07]
* feat(publish): disabled Publish with a reason, Publication section in project settings [e75077088]
* fix(publish): let the viewer's nginx pass a project bundle to the API [64328ce7a]
* fix(publish): wait for the target's answer as long as a multi-GB bundle needs [1649bc492]
* fix(sharing): let owners and P.I.s who are not admins find people to share a project with [624407e7f]
* fix(publish): send the files of an image collection with the project [3ff9d12ec]
* fix(ingestion): register a GeoJSON collection without reading a Delta log [2e91c81dd]
* feat(figures): option to refuse new figure code from non-admin users ([#1374](https://github.com/depictio/depictio/pull/1374)) [4be5e8b13]
* fix(from-run): keep the tiles of optional collections queued for ingestion ([#1373](https://github.com/depictio/depictio/pull/1373)) [c0d0a5f4e]
* feat(devcontainer): add a Codespace for the hands-on workshop ([#1372](https://github.com/depictio/depictio/pull/1372)) [977cc0082]
* Update CHANGELOG.md for v1.21.0-b1 [90c362b01]


</details>

### Documentation 📖

For more details, please refer to the [documentation](https://depictio.github.io/depictio-docs/)

### Docker Images 🐳

```plaintext
ghcr.io/depictio/depictio:1.21.0-b1
ghcr.io/depictio/depictio:latest
ghcr.io/depictio/depictio:stable
ghcr.io/depictio/depictio:edge
```


<details>
<summary>Click to expand the changelog for 1.21.0-b1</summary>

### Changes 📜

#### Improvements 🚀

* style: sort the test_local_compose imports [782a84907]

#### Documentation Updates 📚

* docs: redraw SSO diagrams for OIDC, note OIDC in the repo guide [106a9d801]

#### Other Changes 📝

* Bump version: 1.20.5 → 1.21.0-b1 [8489f9ef7]
* test(publish): every collection type, logos and comments round trip, compatibility check ([#1303](https://github.com/depictio/depictio/pull/1303)) [db676761e]
* feat(publish): carry dashboard logos and comment threads, refuse what the target cannot render ([#1303](https://github.com/depictio/depictio/pull/1303)) [3ba33afa9]
* fix(viewer): offer Revoke on active invite codes only ([#1303](https://github.com/depictio/depictio/pull/1303)) [744dd0941]
* feat(publish): one kind of invite code: a project, then its updates ([#1303](https://github.com/depictio/depictio/pull/1303)) [90bf1ddbf]
* fix(viewer): a fresh invite code for a project already published says how to update it ([#1303](https://github.com/depictio/depictio/pull/1303)) [adb3518e5]
* ci(helm): pull mongo from Google's Docker Hub mirror in the chart test [c5262bc27]
* feat(publish): plain invite wording, and say how to update a project brought by a code ([#1303](https://github.com/depictio/depictio/pull/1303)) [78dda07fa]
* fix(backup): list migration_invites with the other migration ledgers ([#1303](https://github.com/depictio/depictio/pull/1303)) [f24087651]
* feat(viewer): receive a project, publish to a URL + code, push tracking ([#1303](https://github.com/depictio/depictio/pull/1303)) [0e837df93]
* test(publish): invites, invite push, push tracking, recovery, chart defaults ([#1303](https://github.com/depictio/depictio/pull/1303)) [27b9958cf]
* feat(publish): invite codes, publish to a URL + code, push tracking ([#1303](https://github.com/depictio/depictio/pull/1303)) [f0c0cbdb4]
* test(multiqc): stop a monkeypatch from leaking load_deltatable_lite's mock [dfd1389da]
* chore(helm): name the commit that removed SAML in the backup README [eccb62a0c]
* test(auth): OIDC verification, flow, settings and provisioning; match SSO email ignoring case [197847f72]
* feat(viewer): one sign-in button per OIDC provider [de0100348]
* test(sarek): stop the mapping-only tests waiting on a MongoDB that is not there [66c402417]
* chore(helm,docker): OIDC provider config, back up and migrate SAML values [099ecf726]
* fix(auth): accept Google's documented second iss spelling [a4fff6ec1]
* feat(auth): replace SAML and Google OAuth with generic OIDC SSO (API core) [a6998b1b9]
* feat(publish): push a project to another instance, approve it there, serve it read-only ([#1334](https://github.com/depictio/depictio/pull/1334)) [12f4efa4f]
* Update CHANGELOG.md for v1.20.5 [09164a8f4]
* docs(gcs): reading from GCS is supported, GCS as instance storage is not yet [c312a61a0]
* fix(compose): let glibc own rseq so mongo starts on Linux 6.19+ [128dfca85]
* fix(compose): run mongo 8.0.34, which starts on Linux 6.19+ kernels [65099ee21]
* fix(cli): keep remote_storage_options from the CLI configuration [29df5a788]
* feat(s3): make the S3 clients work on Google Cloud Storage's XML API [a2b640dae]


</details>

### Documentation 📖

For more details, please refer to the [documentation](https://depictio.github.io/depictio-docs/)

### Docker Images 🐳

```plaintext
ghcr.io/depictio/depictio:1.20.5
ghcr.io/depictio/depictio:latest
ghcr.io/depictio/depictio:stable
ghcr.io/depictio/depictio:edge
```


<details>
<summary>Click to expand the changelog for 1.20.5</summary>

### Changes 📜

#### Other Changes 📝

* Bump version: 1.20.4 → 1.20.5 [ac2c6a981]
* fix(nf-core): thresholds and windows follow their tool or a cited source ([#1340](https://github.com/depictio/depictio/pull/1340)) [1e7dd4c9e]
* feat(advanced-viz): rename stacked_taxonomy to stacked_bar, add click selection ([#1339](https://github.com/depictio/depictio/pull/1339)) [eace76cfd]
* fix(advanced_viz): genome_view keeps its strongest rows by a data-defined cut-off ([#1338](https://github.com/depictio/depictio/pull/1338)) [3a2385bc5]
* fix(dashboards): keep a section's highlights when its one data-bound tile is pruned ([#1337](https://github.com/depictio/depictio/pull/1337)) [5d34d0f41]
* fix(ampliseq): regenerate reference_extended.yaml from base.yaml ([#1341](https://github.com/depictio/depictio/pull/1341)) [5910ccb90]
* Update CHANGELOG.md for v1.20.4 [51883f4db]


</details>

### Documentation 📖

For more details, please refer to the [documentation](https://depictio.github.io/depictio-docs/)

### Docker Images 🐳

```plaintext
ghcr.io/depictio/depictio:1.20.4
ghcr.io/depictio/depictio:latest
ghcr.io/depictio/depictio:stable
ghcr.io/depictio/depictio:edge
```


<details>
<summary>Click to expand the changelog for 1.20.4</summary>

### Changes 📜

#### Other Changes 📝

* Bump version: 1.20.3 → 1.20.4 [8d95d31a0]
* feat(nf-core): colour keys and chart descriptions across the Overview rework templates [155bca6e8]
* feat(api): a text line citing a column its collection lacks is removed on import [305ad1413]
* feat(viewer): a text tile prints one colour key per column, named in the placeholder [c732ec7f9]
* feat(nf-core): review round on hlatyping, viralmetagenome, genomeqc, epitopeprediction and stableexpression [0128ddaee]
* feat(viewer): colour codes in tables and text tiles, zoom axis break, allele grid controls [95d49c3b7]
* feat(viewer): one error card for a page that cannot load ([#1329](https://github.com/depictio/depictio/pull/1329)) [60b775bd7]
* feat(viewer): describe a tile in a structured info popover ([#1328](https://github.com/depictio/depictio/pull/1328)) [b6eb301eb]
* fix(deps): keep kombu below 5.7 while redis-py is held at 5.2.1 ([#1331](https://github.com/depictio/depictio/pull/1331)) [7426e5797]
* Update CHANGELOG.md for v1.20.3 [76c99b282]


</details>

### Documentation 📖

For more details, please refer to the [documentation](https://depictio.github.io/depictio-docs/)


---

Older releases: https://github.com/depictio/depictio/releases (this file keeps the latest releases; the full text is in git history).
