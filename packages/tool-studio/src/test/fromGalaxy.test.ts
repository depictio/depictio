import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  canonicalGalaxyUrl,
  toolXmlUrl,
  parseGalaxyOutputs,
  fetchGalaxyMeta,
} from '../catalog/fromGalaxy';

describe('canonicalGalaxyUrl', () => {
  it('trims whitespace and trailing slashes, keeping the .xml blob path', () => {
    expect(
      canonicalGalaxyUrl(
        '  https://github.com/galaxyproject/tools-iuc/blob/main/tools/seqtk/seqtk_seq.xml/ ',
      ),
    ).toBe('https://github.com/galaxyproject/tools-iuc/blob/main/tools/seqtk/seqtk_seq.xml');
  });
});

describe('toolXmlUrl', () => {
  it('maps a GitHub blob URL to raw.githubusercontent.com', () => {
    expect(
      toolXmlUrl('https://github.com/galaxyproject/tools-iuc/blob/main/tools/seqtk/seqtk_seq.xml'),
    ).toBe(
      'https://raw.githubusercontent.com/galaxyproject/tools-iuc/main/tools/seqtk/seqtk_seq.xml',
    );
  });
});

const parse = (xml: string) => new DOMParser().parseFromString(xml, 'application/xml');

describe('parseGalaxyOutputs', () => {
  it('prefers from_work_dir, falls back to *.<format>, and skips dynamic formats', () => {
    const doc = parse(`<tool><outputs>
      <data name="report" format="tabular" label="Report" />
      <data name="log" from_work_dir="run.log" format="txt" />
      <data name="dynamic" format="auto" />
    </outputs></tool>`);
    expect(parseGalaxyOutputs(doc)).toEqual([
      { name: 'report', pattern: '*.tabular', description: 'Report', type: 'file' },
      { name: 'log', pattern: 'run.log', description: '', type: 'file' },
      { name: 'dynamic', pattern: '', description: '', type: 'file' },
    ]);
  });

  it('drops macro/Cheetah-template labels rather than surfacing them as descriptions', () => {
    const doc = parse(`<tool><outputs>
      <data name="default" format="auto" label="\${tool.name} on \${on_string}" />
    </outputs></tool>`);
    expect(parseGalaxyOutputs(doc)).toEqual([
      { name: 'default', pattern: '', description: '', type: 'file' },
    ]);
  });
});

const SAMPLE = `<tool id="seqtk_seq" name="seqtk_seq" version="1.0">
  <description>common transformation of FASTA/Q</description>
  <xrefs>
    <xref type="bio.tools">seqtk</xref>
  </xrefs>
  <outputs>
    <data name="default" format="fasta" label="output" />
  </outputs>
</tool>`;

describe('fetchGalaxyMeta', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('extracts id/name/description, inline bio.tools xref and outputs', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(SAMPLE, { status: 200 })),
    );
    const meta = await fetchGalaxyMeta(
      'https://github.com/galaxyproject/tools-iuc/blob/main/tools/seqtk/seqtk_seq.xml',
    );
    expect(meta.name).toBe('seqtk_seq');
    expect(meta.description).toBe('common transformation of FASTA/Q');
    expect(meta.biotools_url).toBe('https://bio.tools/seqtk');
    expect(meta.homepage).toBe('');
    expect(meta.source_url).toContain('tools/seqtk/seqtk_seq.xml');
    expect(meta.outputs).toEqual([
      { name: 'default', pattern: '*.fasta', description: 'output', type: 'file' },
    ]);
  });

  it('falls back to the id when the name is a macro token', async () => {
    const macroName = SAMPLE.replace('name="seqtk_seq"', 'name="@TOOL_NAME@"');
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(macroName, { status: 200 })),
    );
    const meta = await fetchGalaxyMeta(
      'https://github.com/galaxyproject/tools-iuc/blob/main/tools/seqtk/seqtk_seq.xml',
    );
    expect(meta.name).toBe('seqtk_seq');
  });

  it('raises on a non-OK response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('', { status: 404 })),
    );
    await expect(
      fetchGalaxyMeta('https://github.com/galaxyproject/tools-iuc/blob/main/tools/x/x.xml'),
    ).rejects.toThrow(/HTTP 404/);
  });
});
