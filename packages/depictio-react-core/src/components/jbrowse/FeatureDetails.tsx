import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  CopyButton,
  Group,
  Modal,
  ScrollArea,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { reaction } from 'mobx';

import { Z_LAYERS } from '../../zLayers';
import { useFullscreenPortalTarget } from '../chrome/useFullscreenPortalTarget';
import {
  buildFeatureView,
  isFeatureWidgetType,
  type AnnotationRow,
  type ChipGroup,
  type Fact,
  type FeatureView,
  type GenotypeRow,
} from './featureDetailsModel';

/** Annotation rows shown before "show N more". */
const ANNOTATION_PREVIEW = 5;
/** Genotype rows shown before "show N more" (a cohort VCF has hundreds). */
const GENOTYPE_PREVIEW = 12;

interface WidgetLike {
  type?: string;
  featureData?: unknown;
  unformattedFeatureData?: unknown;
  descriptions?: unknown;
  track?: { configuration?: unknown } | null;
}

interface SessionLike {
  visibleWidget?: WidgetLike;
  hideAllWidgets: () => void;
}

interface Shown {
  view: FeatureView;
  trackName?: string;
}

interface Props {
  /** The JBrowse session whose feature widgets are replaced by this panel. */
  session: SessionLike;
  /** The track's display name, read at click time (`readConfObject(track.configuration, 'name')`). */
  trackNameOf?: (track: WidgetLike['track']) => string | undefined;
  /** True while a feature widget must be left alone: the click-to-filter
   *  reaction owns it (hides it and emits a dashboard filter). */
  leaveWidget: (widgetType: string) => boolean;
}

const PortalCtx = createContext<HTMLElement | undefined>(undefined);

/** A tooltip above the modal (Mantine's default layer sits behind it), in the
 *  fullscreen element when the tile is fullscreen. */
const Tip: React.FC<React.ComponentProps<typeof Tooltip>> = (props) => {
  const target = useContext(PortalCtx);
  return <Tooltip zIndex={Z_LAYERS.tooltip} portalProps={{ target }} {...props} />;
};

/** Text cut to `maw` px with the full value in a tooltip once it is long. */
const Trunc: React.FC<{ text: string; maw?: number; mono?: boolean; hint?: string; fw?: number }> = ({
  text,
  maw = 220,
  mono,
  hint,
  fw,
}) => {
  const long = text.length > Math.floor(maw / (mono ? 7.5 : 6.5));
  const label = long ? text : hint;
  const node = (
    <Text
      component="span"
      size="sm"
      fw={fw}
      ff={mono ? 'monospace' : undefined}
      truncate="end"
      maw={maw}
      style={{ display: 'block' }}
    >
      {text}
    </Text>
  );
  if (!label) return node;
  return (
    <Tip label={label} multiline maw={360} openDelay={150} style={{ wordBreak: 'break-all' }}>
      {node}
    </Tip>
  );
};

const TH: React.CSSProperties = {
  fontWeight: 600,
  fontSize: 'var(--mantine-font-size-xs)',
  color: 'var(--mantine-color-dimmed)',
};

const Heading: React.FC<{ children: React.ReactNode; right?: React.ReactNode }> = ({ children, right }) => (
  <Group justify="space-between" mb={4} wrap="nowrap">
    <Text size="xs" fw={600} c="dimmed" tt="uppercase" style={{ letterSpacing: 0.4 }}>
      {children}
    </Text>
    {right}
  </Group>
);

const FactCell: React.FC<{ fact: Fact }> = ({ fact }) => (
  <div style={{ minWidth: 0 }}>
    <Text size="xs" c="dimmed">
      {fact.label}
    </Text>
    {fact.tone ? (
      <Badge variant="light" color={fact.tone} size="md" radius="sm" tt="none" mt={2} style={{ maxWidth: '100%' }}>
        {fact.value}
      </Badge>
    ) : (
      <Trunc text={fact.value} mono={fact.mono} hint={fact.hint} maw={200} fw={500} />
    )}
  </div>
);

const ChipRow: React.FC<{ group: ChipGroup }> = ({ group }) => (
  <Group gap={6} align="center">
    <Text size="xs" c="dimmed" style={{ minWidth: 68 }}>
      {group.label}
    </Text>
    {group.chips.map((chip) => {
      const badge = (
        <Badge key={chip.text} variant="light" color={chip.tone ?? 'gray'} size="md" radius="sm" tt="none">
          {chip.text}
        </Badge>
      );
      return chip.hint ? (
        <Tip key={chip.text} label={chip.hint}>
          {badge}
        </Tip>
      ) : (
        badge
      );
    })}
  </Group>
);

const MoreButton: React.FC<{ hidden: number; expanded: boolean; onToggle: () => void }> = ({
  hidden,
  expanded,
  onToggle,
}) =>
  hidden > 0 || expanded ? (
    <Button variant="subtle" size="compact-xs" color="gray" mt={4} onClick={onToggle}>
      {expanded ? 'Show fewer' : `Show ${hidden} more`}
    </Button>
  ) : null;

const AnnotationsTable: React.FC<{ rows: AnnotationRow[]; source: 'CSQ' | 'ANN' }> = ({ rows, source }) => {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, ANNOTATION_PREVIEW);
  return (
    <div>
      <Heading>{source === 'CSQ' ? 'VEP annotations' : 'snpEff annotations'}</Heading>
      <Table withRowBorders verticalSpacing={4} horizontalSpacing="xs" fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th style={TH}>Gene</Table.Th>
            <Table.Th style={TH}>Consequence</Table.Th>
            <Table.Th style={TH}>Impact</Table.Th>
            <Table.Th style={TH}>HGVSc</Table.Th>
            <Table.Th style={TH}>HGVSp</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {shown.map((a, i) => (
            <Table.Tr key={`${a.gene}-${a.hgvsc}-${a.consequence}-${i}`}>
              <Table.Td>
                <Trunc text={a.gene || '-'} maw={100} fw={500} />
              </Table.Td>
              <Table.Td>
                <Trunc text={a.consequence || '-'} maw={230} />
              </Table.Td>
              <Table.Td>
                {a.impact ? (
                  <Badge variant="light" color={a.impactTone} size="sm" radius="sm" tt="none">
                    {a.impact}
                  </Badge>
                ) : (
                  '-'
                )}
              </Table.Td>
              <Table.Td>
                <Trunc text={a.hgvsc || '-'} maw={110} mono hint={a.hgvscFull !== a.hgvsc ? a.hgvscFull : undefined} />
              </Table.Td>
              <Table.Td>
                <Trunc text={a.hgvsp || '-'} maw={110} mono hint={a.hgvspFull !== a.hgvsp ? a.hgvspFull : undefined} />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <MoreButton
        hidden={rows.length - ANNOTATION_PREVIEW}
        expanded={all}
        onToggle={() => setAll((v) => !v)}
      />
    </div>
  );
};

const GenotypesTable: React.FC<{ rows: GenotypeRow[] }> = ({ rows }) => {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, GENOTYPE_PREVIEW);
  const num = { textAlign: 'right' } as const;
  return (
    <div>
      <Heading>Genotypes</Heading>
      <Table withRowBorders verticalSpacing={4} horizontalSpacing="xs" fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th style={TH}>Sample</Table.Th>
            <Table.Th style={TH}>Genotype</Table.Th>
            <Table.Th style={{ ...TH, ...num }}>DP</Table.Th>
            <Table.Th style={{ ...TH, ...num }}>GQ</Table.Th>
            <Table.Th style={{ ...TH, ...num }}>AD</Table.Th>
            <Table.Th style={{ ...TH, ...num }}>VAF</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {shown.map((g) => (
            <Table.Tr key={g.sample}>
              <Table.Td>
                <Trunc text={g.sample} maw={150} fw={500} />
              </Table.Td>
              <Table.Td>
                <Tip label={g.gt} withArrow>
                  <Badge
                    variant={g.tone === 'gray' ? 'outline' : 'light'}
                    color={g.tone}
                    size="sm"
                    radius="sm"
                    tt="none"
                  >
                    {g.zygosityLabel}
                  </Badge>
                </Tip>
              </Table.Td>
              <Table.Td style={num}>{g.dp || '-'}</Table.Td>
              <Table.Td style={num}>{g.gq || '-'}</Table.Td>
              <Table.Td style={num}>{g.ad || '-'}</Table.Td>
              <Table.Td style={num}>{g.vaf || '-'}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <MoreButton hidden={rows.length - GENOTYPE_PREVIEW} expanded={all} onToggle={() => setAll((v) => !v)} />
    </div>
  );
};

const AllFields: React.FC<{ fields: FeatureView['fields'] }> = ({ fields }) => {
  const [open, setOpen] = useState(false);
  if (fields.length === 0) return null;
  return (
    <div>
      <Button
        variant="subtle"
        color="gray"
        size="compact-sm"
        onClick={() => setOpen((v) => !v)}
        leftSection={<Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} height={16} />}
        aria-expanded={open}
      >
        All fields ({fields.length})
      </Button>
      {open ? (
        <Table withRowBorders verticalSpacing={3} horizontalSpacing="xs" fz="xs" mt={4}>
          <Table.Tbody>
            {fields.map((f, i) => (
              <Table.Tr key={`${f.key}-${i}`}>
                <Table.Td style={{ width: '32%', verticalAlign: 'top' }}>
                  <Text size="xs" c="dimmed" style={{ wordBreak: 'break-word' }}>
                    {f.key}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Trunc text={f.value} maw={430} mono />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
    </div>
  );
};

const Header: React.FC<{ view: FeatureView; trackName?: string }> = ({ view, trackName }) => (
  <Stack gap={2} style={{ minWidth: 0 }}>
    <Group gap="xs" wrap="nowrap" align="center">
      <Text fw={600} size="lg" truncate="end" style={{ minWidth: 0 }}>
        {view.title}
      </Text>
      <Badge variant="light" size="md" radius="sm" tt="none" style={{ flexShrink: 0 }}>
        {view.typeLabel}
      </Badge>
    </Group>
    <Group gap={4} wrap="nowrap">
      <Text size="sm" c="dimmed" ff="monospace">
        {view.locus}
      </Text>
      <CopyButton value={view.locus} timeout={1500}>
        {({ copied, copy }) => (
          <Tip label={copied ? 'Copied' : 'Copy locus'} withArrow>
            <ActionIcon
              variant="subtle"
              color={copied ? 'teal' : 'gray'}
              size="sm"
              onClick={copy}
              aria-label="Copy the locus"
            >
              <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} height={14} />
            </ActionIcon>
          </Tip>
        )}
      </CopyButton>
    </Group>
    {view.subtitle || trackName ? (
      <Text size="xs" c="dimmed" truncate="end">
        {[view.subtitle, trackName].filter(Boolean).join('  ·  ')}
      </Text>
    ) : null}
  </Stack>
);

const Body: React.FC<{ view: FeatureView }> = ({ view }) => (
  // data-autofocus: the modal's focus trap lands here, not on the copy button.
  <Stack gap="md" data-autofocus tabIndex={-1} style={{ outline: 'none' }}>
    {view.facts.length > 0 ? (
      <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm" verticalSpacing="sm">
        {view.facts.map((f) => (
          <FactCell key={f.label} fact={f} />
        ))}
      </SimpleGrid>
    ) : null}
    {view.description ? <Text size="sm">{view.description}</Text> : null}
    {view.chips.map((g) => (
      <ChipRow key={g.label} group={g} />
    ))}
    {view.annotations.length > 0 && view.annotationSource ? (
      <AnnotationsTable rows={view.annotations} source={view.annotationSource} />
    ) : null}
    {view.genotypes.length > 0 ? <GenotypesTable rows={view.genotypes} /> : null}
    <AllFields fields={view.fields} />
  </Stack>
);

/**
 * Depictio's replacement for JBrowse's feature details drawer.
 *
 * JBrowse opens a feature widget (`BaseFeatureWidget`, `VariantFeatureWidget`,
 * `AlignmentsFeatureWidget`) when a feature is clicked. A MobX reaction on
 * `session.visibleWidget` copies the widget's `featureData` (plain JSON), hides
 * the widget so `ModalWidget` renders nothing for it, and shows the data in a
 * Mantine modal: portaled out of the tile (which clips its children) and, in
 * native fullscreen, into the fullscreen element. Every other widget keeps
 * JBrowse's own dialog.
 */
const FeatureDetails: React.FC<Props> = ({ session, trackNameOf, leaveWidget }) => {
  const [shown, setShown] = useState<Shown | null>(null);
  const portalTarget = useFullscreenPortalTarget();
  const leaveRef = useRef(leaveWidget);
  leaveRef.current = leaveWidget;
  const nameRef = useRef(trackNameOf);
  nameRef.current = trackNameOf;

  useEffect(
    () =>
      reaction(
        () => session.visibleWidget,
        (widget) => {
          if (!widget || !isFeatureWidgetType(widget.type)) return;
          if (leaveRef.current(widget.type as string)) return;
          const raw = widget.featureData ?? widget.unformattedFeatureData;
          if (!raw || typeof raw !== 'object') return;
          let data: Record<string, unknown>;
          let descriptions: unknown;
          try {
            data = JSON.parse(JSON.stringify(raw));
            descriptions = widget.descriptions ? JSON.parse(JSON.stringify(widget.descriptions)) : undefined;
          } catch {
            return; // not plain JSON: leave JBrowse's drawer to show it
          }
          let trackName: string | undefined;
          try {
            trackName = nameRef.current?.(widget.track);
          } catch {
            trackName = undefined;
          }
          let view: FeatureView;
          try {
            view = buildFeatureView(data, { descriptions, widgetType: widget.type });
          } catch (e) {
            console.error('Feature panel could not read the feature; showing JBrowse details', e);
            return;
          }
          session.hideAllWidgets();
          setShown({ view, trackName });
        },
      ),
    [session],
  );

  const view = shown?.view;
  const header = useMemo(
    () => (view ? <Header view={view} trackName={shown?.trackName} /> : null),
    [view, shown?.trackName],
  );

  return (
    <PortalCtx.Provider value={portalTarget}>
      <Modal
        opened={shown != null}
        onClose={() => setShown(null)}
        centered
        size={720}
        title={header}
        scrollAreaComponent={ScrollArea.Autosize}
        portalProps={{ target: portalTarget }}
        overlayProps={{ backgroundOpacity: 0.35 }}
        keepMounted={false}
        zIndex={Z_LAYERS.overlay}
        styles={{ title: { flex: 1, minWidth: 0 } }}
        data-testid="jbrowse-feature-details"
      >
        {view ? <Body view={view} /> : null}
      </Modal>
    </PortalCtx.Provider>
  );
};

export default FeatureDetails;
