import React from 'react';
import { Tooltip } from '@mantine/core';

import { splitStepValue, type Step } from './blockMarkdown';
import Glyph from './Glyph';
import './stepFlow.css';

/**
 * The list of a `::: steps` div — `1. ![](icon:mdi:dna) **Amplicon** V4–V5` —
 * drawn as the steps of a process: marks joined by a rail (an item's icon, or
 * its number), each step's label over its value. A pipeline summary read as a table loses its order, the one
 * thing that explains it; read as a flow it says what was done to the data,
 * in the order it was done.
 *
 * Across the tile when it is wide enough, down it when not (a container
 * query in stepFlow.css): five steps side by side on a phone would leave a
 * word per line.
 */
/** `[Settings](params:x)` → `Settings`: the name an icon-only link shows on hover. */
function linkLabel(link: string): string {
  return link.match(/^\[([^\]]*)\]/)?.[1] ?? link;
}

const StepFlow: React.FC<{
  steps: Step[];
  inline: (text: string) => React.ReactNode[];
  /** The marks' colour; the theme's primary when the tile sets none. */
  accentColor?: string | null;
}> = ({ steps, inline, accentColor }) => {
  // A step without a label keeps the label's line when others have one, so
  // the values stay on one line across the flow.
  const labelled = steps.some((step) => step.label);
  return (
    <div className="depictio-step-flow-box">
      <ol
        className="depictio-step-flow"
        style={
          {
            '--step-accent': accentColor ?? 'var(--mantine-primary-color-filled)',
          } as React.CSSProperties
        }
      >
        {steps.map((step, i) => {
          const { text, links } = splitStepValue(step.value);
          return (
            <li key={i} className="depictio-step">
              <span className="depictio-step-rail" aria-hidden>
                <span className="depictio-step-mark">
                  {step.icon ? <Glyph icon={step.icon} color="currentColor" size={18} /> : i + 1}
                </span>
                <span className="depictio-step-line" />
              </span>
              <span className="depictio-step-body">
                {(labelled || links.length > 0) && (
                  <span className="depictio-step-head">
                    <span className="depictio-step-label">{step.label || '\u00a0'}</span>
                    {links.length > 0 && (
                      // The parameters and tabs behind a step, as small icons
                      // beside its name: there when looked for, out of the way of
                      // the value, which is what the step says.
                      <span className="depictio-step-links">
                        {links.map((link, j) => {
                          const name = linkLabel(link);
                          return (
                            <Tooltip key={j} label={name} withArrow openDelay={150}>
                              <span className="depictio-step-link" aria-label={name}>
                                {inline(link)}
                              </span>
                            </Tooltip>
                          );
                        })}
                      </span>
                    )}
                  </span>
                )}
                <span className="depictio-step-value">{inline(text)}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
};

export default StepFlow;
