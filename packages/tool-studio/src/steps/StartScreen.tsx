/**
 * What this app is, before any form.
 *
 * The wizard used to open straight on the Tool step: two panels of `slug` and
 * `path_glob` with the explanation squeezed into grey fine print above them.
 * Someone arriving from a link had to reverse-engineer what a catalog entry is
 * from the fields that build one. This screen answers that first: what an entry
 * does for people who run the tool, the four steps it takes, and what it does
 * not cover.
 *
 * It is drawn as depictio's component builder draws its own start screen (the
 * Paper `bgl-choice` hero and `bgl-tile` cards of builder/glass/builder-glass.css):
 * a centred title and lead, the two ways in, then the four steps as tiles, each
 * in its own hue, and the scope as two quiet cards under them.
 *
 * Shown once per draft: `started` is persisted, so a refresh mid-entry returns
 * to the work rather than to the pitch, and `Start over` (which resets the
 * draft) brings the screen back.
 */
import React from 'react';
import { Badge, Button } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { ArrowRight, ShieldCheck } from 'lucide-react';
import ImportEntryButton from '../components/ImportEntryButton';
import { STEP_ICONS } from '../components/StepHead';
import { PRIVACY_LINE, DOCS_URL, CATALOG_URL, ISSUES_URL } from '../components/AppHeader';
import { draftFromCatalogFiles } from '../catalog/draft';
import { EXAMPLE_FILES, EXAMPLE_LABEL } from '../catalog/example';
import { useStudioStore } from '../state/useStudioStore';
import { STUDIO_TONE } from '../theme';

/** One hue per step, carried by its glyph well, so the four are told apart at
 *  a glance rather than only read in order. */
const STEPS = [
  {
    color: 'violet',
    title: 'Tool',
    body: 'Name the tool and the output file this entry describes. nf-core, Snakemake and Galaxy prefill it from a URL.',
  },
  {
    color: 'blue',
    title: 'Fixture',
    body: 'Drop one sample of that file. It is read in this page, and ships with the entry as the example CI checks against.',
  },
  {
    color: 'teal',
    title: 'Visualizations',
    body: "Bind its columns in depictio's own component builder: cards, figures, tables, filters, advanced plots.",
  },
  {
    color: 'pink',
    title: 'Export',
    body: 'Download the entry as a zip, or sign in and open the pull request against depictio in one click.',
  },
] as const;

const tint = (color: string) =>
  ({ ['--bgl-tint' as string]: `var(--mantine-color-${color}-6)` }) as React.CSSProperties;

export default function StartScreen({ onStart, resuming }: { onStart: () => void; resuming?: boolean }) {
  const loadDraft = useStudioStore((s) => s.loadDraft);
  // A complete, committed entry to walk through before writing one: it lands
  // on the Tool step so every step can be read in order.
  const loadExample = () => {
    const { draft } = draftFromCatalogFiles(EXAMPLE_FILES);
    loadDraft(draft, 0);
    notifications.show({
      color: 'teal',
      autoClose: 12000,
      title: `Example loaded: ${EXAMPLE_LABEL}`,
      message:
        'Walk through the four steps to see a finished entry. The raw mosdepth file is not bundled, so the recipe shows its committed result. Click the logo, top left, then Start over to write your own.',
    });
  };
  const sha = __BUILD_SHA__;
  return (
    <section className="bgl-choice ts-start" data-testid="start-screen">
      <div className="bgl-choice-hero">
        <h1 className="bgl-choice-title">Add a tool to the Depictio Tools Catalog</h1>
        <p className="bgl-choice-lead">
          An entry teaches depictio to recognise one output file of a tool and to turn it into
          ready-made dashboard components for everyone who runs it.
        </p>
      </div>

      <div className="ts-start-actions">
        <Button
          color={STUDIO_TONE}
          onClick={onStart}
          rightSection={<ArrowRight size={18} strokeWidth={1.9} aria-hidden />}
          data-testid="start"
        >
          {resuming ? 'Continue' : 'Start'}
        </Button>
        <Button
          variant="default"
          onClick={loadExample}
          leftSection={<Icon icon="mdi:lightbulb-on-outline" width={18} />}
          data-testid="load-example"
        >
          Try an example
        </Button>
        <ImportEntryButton variant="default" />
      </div>

      <ol className="ts-steps" aria-label="The four steps">
        {STEPS.map((s, i) => (
          <li key={s.title} className="bgl-tile" style={tint(s.color)}>
            <span className="bgl-tile-icon" aria-hidden>
              <Icon icon={STEP_ICONS[i]} width={26} />
            </span>
            <span>
              <span className="ts-step-num">Step {i + 1}</span>
              <span className="bgl-tile-label" style={{ display: 'block' }}>
                {s.title}
              </span>
              <span className="bgl-tile-desc" style={{ display: 'block', marginInline: 'auto' }}>
                {s.body}
              </span>
            </span>
          </li>
        ))}
      </ol>

      {/* Scope, as two facing cards. Half the committed catalog outputs need a
          parsing recipe, and someone who came to describe one of those should
          learn it here, not three steps in with a file that will not parse. */}
      <div className="ts-scope">
        <div className="ts-scope-card">
          <span className="bgl-tile-icon" style={tint('teal')} aria-hidden>
            <Icon icon="mdi:table-check" width={22} />
          </span>
          <div>
            <p className="ts-scope-title">Tables directly</p>
            <p className="ts-scope-desc">when the output file is already a table with a header row.</p>
          </div>
        </div>
        <div className="ts-scope-card">
          <span className="bgl-tile-icon" style={tint('blue')} aria-hidden>
            <Icon icon="mdi:language-python" width={22} />
          </span>
          <div>
            <p className="ts-scope-title">Anything else, with a recipe</p>
            <p className="ts-scope-desc">
              when it needs reshaping first: write the polars recipe here and run it on a sample, in
              your browser.
            </p>
          </div>
        </div>
      </div>

      <p className="bgl-choice-note" data-testid="privacy-note">
        <ShieldCheck size={14} strokeWidth={1.8} aria-hidden />
        {PRIVACY_LINE}
      </p>

      {/* Which build this is, and where to go from here: a static site has no
          other way to say it, and on the landing it should not hide behind the
          About key. */}
      <footer className="ts-start-foot" data-testid="landing-footer">
        <span className="ts-start-foot-build">
          <Badge size="xs" variant="light" color="violet" radius="sm">
            beta
          </Badge>
          <span>
            Studio v{__STUDIO_VERSION__} · depictio v{__DEPICTIO_VERSION__}
            {sha ? ` (${sha})` : ''}
          </span>
        </span>
        <nav className="ts-start-foot-links" aria-label="Tool Studio links">
          <a href={DOCS_URL} target="_blank" rel="noreferrer">
            Docs
          </a>
          <a href={CATALOG_URL} target="_blank" rel="noreferrer">
            Catalog
          </a>
          <a href={ISSUES_URL} target="_blank" rel="noreferrer">
            Report an issue
          </a>
        </nav>
      </footer>
    </section>
  );
}
