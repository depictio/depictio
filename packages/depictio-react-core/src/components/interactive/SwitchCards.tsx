import React from 'react';
import { Icon } from '@iconify/react';

import './switchCards.css';

export interface SwitchCardOption {
  value: string;
  label: string;
  icon?: string;
  description?: string;
  disabled?: boolean;
}

/**
 * One card per option, the open one lit in the accent: the page-level switch of
 * the project page (Data collections / Ingestion report) as a dashboard filter.
 * For a choice that changes what a whole tab shows, where a row of bare labels
 * does not say what the reader gets.
 *
 * The icons are bundled by scanning the source for `prefix:name` literals, so a
 * dashboard that names one needs it written somewhere in a scanned tree: the TREC
 * dashboard's cards use 'mdi:set-merge', 'mdi:bacteria-outline' and
 * 'mdi:jellyfish-outline'.
 *
 * A radio group, not tabs: it filters one data collection, it does not open a
 * panel.
 */
const SwitchCards: React.FC<{
  options: SwitchCardOption[];
  value: string;
  onChange: (value: string) => void;
  label?: string;
  /** CSS colour of the open card (the tab's colour); the chrome's accent when unset. */
  accent?: string;
}> = ({ options, value, onChange, label, accent }) => (
  <div
    className="dp-switch-cards"
    role="radiogroup"
    aria-label={label}
    style={
      {
        gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))`,
        ...(accent ? { '--sc-accent': accent } : null),
      } as React.CSSProperties
    }
  >
    {options.map((o) => {
      const active = o.value === value;
      return (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={active}
          data-active={active || undefined}
          data-testid={`switch-card-${o.value}`}
          disabled={o.disabled}
          className="dp-switch-card"
          onClick={() => onChange(o.value)}
        >
          {o.icon && (
            <span className="dp-switch-card-icon">
              <Icon icon={o.icon} width={22} aria-hidden />
            </span>
          )}
          <span className="dp-switch-card-text">
            <span className="dp-switch-card-label">{o.label}</span>
            {o.description && <span className="dp-switch-card-meta">{o.description}</span>}
          </span>
        </button>
      );
    })}
  </div>
);

export default SwitchCards;
