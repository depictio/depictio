import React from 'react';

import { splitStepValue, type Fact } from './blockMarkdown';
import Glyph from './Glyph';
import './stepFlow.css';

/**
 * A numbered list of facts — `1. ![](icon:mdi:dna) **Amplicon** V4–V5` —
 * drawn as the steps of a process: marks joined by a rail, each step's label
 * over its value. A pipeline summary read as a table loses its order, the one
 * thing that explains it; read as a flow it says what was done to the data,
 * in the order it was done.
 *
 * Across the tile when it is wide enough, down it when not (a container
 * query in stepFlow.css): five steps side by side on a phone would leave a
 * word per line.
 */
const StepFlow: React.FC<{
  steps: Fact[];
  inline: (text: string) => React.ReactNode[];
  /** The marks' colour; the theme's primary when the tile sets none. */
  accentColor?: string | null;
}> = ({ steps, inline, accentColor }) => (
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
            <span className="depictio-step-label">{step.label}</span>
            <span className="depictio-step-value">{inline(text)}</span>
            {links.length > 0 && (
              // The parameters and tabs behind a step, as pills under its
              // value rather than run into its text.
              <span className="depictio-step-links">
                {links.map((link, j) => (
                  <span key={j} className="depictio-step-link">
                    {inline(link)}
                  </span>
                ))}
              </span>
            )}
          </span>
        </li>
        );
      })}
    </ol>
  </div>
);

export default StepFlow;
