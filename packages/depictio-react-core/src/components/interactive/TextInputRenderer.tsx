import React, { useEffect, useRef, useState } from 'react';
import { CloseButton, TextInput } from '@mantine/core';
import { CompactControlSlot } from 'depictio-components';
import { Icon } from '@iconify/react';

import { InteractiveFilter, StoredMetadata } from '../../api';
import { INTERACTIVE_FRAME, InteractiveFrame, InteractiveTitle, interactiveTitle } from './frame';
import TextFilterMatches from './TextFilterMatches';
import {
  TEXT_FILTER_DEBOUNCE_MS,
  normalizeTextFilterValue,
  regexError,
  textFilterEvent,
} from './textFilter';

/** The pattern the dashboard currently applies for this box. */
function appliedValue(metadata: StoredMetadata, filters: InteractiveFilter[]): string {
  const entry = filters.find((f) => f.index === metadata.index && f.source === undefined);
  return typeof entry?.value === 'string' ? entry.value : '';
}

/**
 * The search box itself, without a frame: shared by the Filters panel
 * (`TextInputRenderer`) and the filter bar.
 *
 * It keeps what the user typed in local state and sends the filter 300 ms
 * after the last keystroke, so a pattern is not recomputed on every key. A
 * pattern that does not compile is flagged under the box and never sent: the
 * data keeps showing the last good filter instead of flashing through the
 * half-typed ones (`[A-`, `(`).
 *
 * The stored value flows back in: a reset, a share link or another tab's state
 * replaces the text, while the box's own echo (the value just sent) leaves it
 * alone, so trailing spaces and the caret survive.
 */
export const TextFilterBox: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
  /** Accessible name of the box. */
  label: string;
  size?: string;
  /** Show the error as a red border and a tooltip only, for a one-line host. */
  bareError?: boolean;
  /** Told the text of the box on every keystroke, applied or not. */
  onType?: (text: string) => void;
}> = ({
  metadata,
  filters,
  onChange,
  label,
  size = INTERACTIVE_FRAME.controlSize,
  bareError,
  onType,
}) => {
  const stored = appliedValue(metadata, filters);
  const [text, setText] = useState(stored);
  // The last value this box sent (or took from the store): what "unchanged"
  // means for both the echo and the debounce.
  const settled = useRef(stored);

  useEffect(() => {
    if (stored !== settled.current) {
      settled.current = stored;
      setText(stored);
    }
  }, [stored]);

  useEffect(() => {
    onType?.(text);
  }, [text, onType]);

  const error = regexError(text, metadata.match_mode);

  useEffect(() => {
    const next = normalizeTextFilterValue(text) ?? '';
    if (next === settled.current || regexError(text, metadata.match_mode)) return;
    const timer = setTimeout(() => {
      const event = textFilterEvent(metadata, text);
      if (!event) return;
      settled.current = next;
      onChange?.(event);
    }, TEXT_FILTER_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // `metadata` is a fresh object per render in some hosts; its fields are
    // what the event reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    text,
    onChange,
    metadata.index,
    metadata.column_name,
    metadata.dc_id,
    metadata.filter_expr,
    metadata.case_sensitive,
    metadata.match_mode,
  ]);

  const clear = () => {
    setText('');
    if (settled.current === '') return;
    settled.current = '';
    const event = textFilterEvent(metadata, '');
    if (event) onChange?.(event);
  };

  return (
    <TextInput
      aria-label={label}
      size={size}
      value={text}
      placeholder={metadata.placeholder || undefined}
      onChange={(e) => setText(e.currentTarget.value)}
      onKeyDown={(e) => {
        // Escape empties the box, and clears the filter without the debounce.
        if (e.key === 'Escape') clear();
      }}
      leftSection={<Icon icon="mdi:magnify" width={16} height={16} />}
      rightSection={
        text !== '' ? <CloseButton size="sm" aria-label="Clear" onClick={clear} /> : undefined
      }
      rightSectionPointerEvents="all"
      autoComplete="off"
      spellCheck={false}
      error={bareError ? Boolean(error) : error}
      title={error ?? undefined}
    />
  );
};

/**
 * TextInput renderer for the React viewer: a search box that filters a string
 * column by a regular expression (`GGG$`, `^ACG`, `A{5,}`; a plain substring
 * is one too). Case is ignored unless the component sets `case_sensitive`;
 * `match_mode: contains` matches the text literally.
 *
 * Emits `{index, value: string | null, column_name, interactive_component_type:
 * 'TextInput', metadata: {dc_id, ...options}}`; an empty box emits `null`,
 * which clears the filter. See `textFilter.ts` for the value rules.
 */
const TextInputRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
  /** Compact rendering: drops the frame, relies on the parent group's card. */
  compact?: boolean;
}> = ({ metadata, filters, onChange, compact }) => {
  // The box's own text, for the match list to follow while it is typed.
  const [typed, setTyped] = useState(() => appliedValue(metadata, filters));
  return (
    <InteractiveFrame compact={compact}>
      <InteractiveTitle metadata={metadata} compact={compact} />
      <CompactControlSlot compact={compact}>
        <TextFilterBox
          metadata={metadata}
          filters={filters}
          onChange={onChange}
          label={interactiveTitle(metadata) || metadata.column_name || 'Text filter'}
          size={compact ? 'xs' : INTERACTIVE_FRAME.controlSize}
          onType={setTyped}
        />
        <TextFilterMatches metadata={metadata} pattern={typed} />
      </CompactControlSlot>
    </InteractiveFrame>
  );
};

export default TextInputRenderer;
