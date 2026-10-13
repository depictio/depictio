/**
 * The control column of a component builder, as collapsible sections.
 *
 * Same look as the Settings drawer (both use `components/settings/
 * SettingsSections`): each section headed by an icon, a title and a one-line
 * subtitle, each field a label, a dimmed description, then the control.
 *
 * Sections start collapsed, except the `required` ones: the fields a component
 * cannot work without (its column, its aggregation, a text tile's body). Those
 * are open on every mount. Which other sections the author opened is
 * remembered per builder type in this browser.
 */
import React from 'react';
import {
  SectionAccordion,
  SettingsSection,
  useOpenSections,
} from '../../components/settings/SettingsSections';

export { Field, SwitchField } from '../../components/settings/SettingsSections';

export const BuilderSections: React.FC<{
  /** Builder type, the key the open sections are remembered under. */
  builder: string;
  /** Sections holding the required fields: open on every mount. */
  required: string[];
  children: React.ReactNode;
}> = ({ builder, required, children }) => {
  const [open, setOpen] = useOpenSections(
    `depictio-builder-sections-open:${builder}`,
    required,
    required,
  );
  return (
    <SectionAccordion value={open} onChange={setOpen} testId={`builder-sections-${builder}`}>
      {children}
    </SectionAccordion>
  );
};

/** One builder section; carries `data-testid="builder-section-<value>"`. */
export const BuilderSection: React.FC<{
  value: string;
  icon: string;
  title: React.ReactNode;
  subtitle: React.ReactNode;
  children: React.ReactNode;
}> = ({ value, icon, title, subtitle, children }) => (
  <SettingsSection
    value={value}
    icon={icon}
    title={title}
    subtitle={subtitle}
    testId={`builder-section-${value}`}
  >
    {children}
  </SettingsSection>
);
