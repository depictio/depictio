import { describe, expect, it } from 'vitest';

import {
  JOIN_NAME_MAX,
  JOIN_TYPE_HELP,
  clearJoinsWarning,
  defaultJoinName,
  defaultJoinSelection,
  deleteJoinedTableNotice,
  deleteJoinsBlock,
  effectiveOnColumns,
  isValidJoinName,
  joinColumnsProblem,
  joinDashboardsSentence,
  joinRebuildNotice,
  joinResultTag,
  joinableTables,
  joinsReadingTable,
  previewSummary,
  readableApiError,
  rightTableOptions,
  unmatchedSentences,
  validateJoinName,
} from '../../src/projects/detail/joinForm';

describe('validateJoinName', () => {
  it('accepts letters, digits, underscores and hyphens', () => {
    expect(validateJoinName('penguins')).toBeNull();
    expect(validateJoinName('Penguins_2-b')).toBeNull();
    expect(isValidJoinName('penguins')).toBe(true);
  });

  it('does not flag an empty name but does not accept it either', () => {
    expect(validateJoinName('')).toBeNull();
    expect(isValidJoinName('')).toBe(false);
  });

  it('rejects spaces and other characters', () => {
    expect(validateJoinName('my join')).toMatch(/Spaces are not allowed/);
    expect(validateJoinName('a.b')).toBe('Use only letters, digits, _ and -');
    expect(validateJoinName('a.b')).not.toBeNull();
    expect(validateJoinName('naïve')).not.toBeNull();
    expect(isValidJoinName('a/b')).toBe(false);
  });

  it('accepts 100 characters and rejects 101', () => {
    expect(validateJoinName('a'.repeat(JOIN_NAME_MAX))).toBeNull();
    expect(validateJoinName('a'.repeat(JOIN_NAME_MAX + 1))).toMatch(/at most 100/);
  });
});

describe('joinResultTag', () => {
  it('prefixes the name with joined_', () => {
    expect(joinResultTag('penguins')).toBe('joined_penguins');
  });
});

describe('JOIN_TYPE_HELP', () => {
  it('explains each join type in plain language', () => {
    expect(JOIN_TYPE_HELP.left).toContain('Keep every row of the left table');
    expect(JOIN_TYPE_HELP.inner).toBe('Keep only the rows found in both tables.');
    expect(JOIN_TYPE_HELP.outer).toBe('Keep every row of both tables, matched where possible.');
    expect(JOIN_TYPE_HELP.right).toContain('Keep every row of the right table');
  });
});

describe('unmatchedSentences', () => {
  const left = { tag: 'demographic_data', unmatched_rows: 12 };
  const right = { tag: 'physical_features', unmatched_rows: 5 };

  it('left join: left rows keep empty values, right rows are left out', () => {
    expect(unmatchedSentences('left', left, right)).toEqual([
      '12 rows of demographic_data have no match in physical_features: their physical_features columns stay empty.',
      '5 rows of physical_features have no match: they are left out.',
    ]);
  });

  it('inner join: unmatched rows of both sides are left out', () => {
    expect(unmatchedSentences('inner', left, right)).toEqual([
      '12 rows of demographic_data have no match: they are left out.',
      '5 rows of physical_features have no match: they are left out.',
    ]);
  });

  it('outer join: both sides are kept with empty values', () => {
    expect(unmatchedSentences('outer', left, right)).toEqual([
      '12 rows of demographic_data have no match in physical_features: their physical_features columns stay empty.',
      '5 rows of physical_features have no match in demographic_data: their demographic_data columns stay empty.',
    ]);
  });

  it('right join: right rows keep empty values, left rows are left out', () => {
    expect(unmatchedSentences('right', left, right)).toEqual([
      '12 rows of demographic_data have no match: they are left out.',
      '5 rows of physical_features have no match in demographic_data: their demographic_data columns stay empty.',
    ]);
  });

  it('says nothing about a side with every row matched and singularises one row', () => {
    expect(
      unmatchedSentences('left', { tag: 'a', unmatched_rows: 0 }, { tag: 'b', unmatched_rows: 1 }),
    ).toEqual(['1 row of b has no match: it is left out.']);
  });

  it('singularises a kept row: "has ... its" versus "have ... their"', () => {
    expect(
      unmatchedSentences('left', { tag: 'a', unmatched_rows: 1 }, { tag: 'b', unmatched_rows: 0 }),
    ).toEqual(['1 row of a has no match in b: its b columns stay empty.']);
    expect(
      unmatchedSentences('left', { tag: 'a', unmatched_rows: 3 }, { tag: 'b', unmatched_rows: 0 }),
    ).toEqual(['3 rows of a have no match in b: their b columns stay empty.']);
    expect(
      unmatchedSentences('left', { tag: 'a', unmatched_rows: 0 }, { tag: 'b', unmatched_rows: 0 }),
    ).toEqual([]);
  });
});

describe('tables and defaults', () => {
  const dcs = [
    { id: '1', tag: 'demographic_data', type: 'table' },
    { id: '2', tag: 'qc', type: 'multiqc' },
    { id: '3', tag: 'physical_features', type: 'Table' },
  ];

  it('keeps tables only', () => {
    expect(joinableTables(dcs).map((d) => d.id)).toEqual(['1', '3']);
  });

  it('preselects the first table on the left with a left join and no columns', () => {
    // No link: the first two tables, the key left to the server's suggestion.
    expect(defaultJoinSelection(joinableTables(dcs))).toEqual({
      leftId: '1',
      rightId: '3',
      how: 'left',
      onColumns: null,
    });
    expect(defaultJoinSelection([]).leftId).toBe('');
    expect(defaultJoinSelection([{ id: 'only', tag: 'only', type: 'table' }]).rightId).toBe('');
  });

  it('preselects the two tables of a link, source on the left', () => {
    const tables = [
      { id: 'phys', tag: 'physical_features', type: 'table' },
      { id: 'demo', tag: 'demographic_data', type: 'table' },
    ];
    const links = [
      { source_dc_id: 'demo', target_dc_id: 'img' }, // not a table: skipped
      { source_dc_id: 'demo', target_dc_id: 'phys' },
    ];
    expect(defaultJoinSelection(tables, links)).toEqual({
      leftId: 'demo',
      rightId: 'phys',
      how: 'left',
      onColumns: null,
    });
  });

  it('without a link, puts the oldest table on the left, whatever the listing order', () => {
    // ObjectIds: creation time first, so demographic_data (…a1) is older.
    const demo = { id: '6b00e14ba8567e9848578ba1', tag: 'demographic_data', type: 'table' };
    const phys = { id: '6b00e14ba8567e9848578ba2', tag: 'physical_features', type: 'table' };
    for (const tables of [[demo, phys], [phys, demo]]) {
      expect(defaultJoinSelection(tables)).toMatchObject({ leftId: demo.id, rightId: phys.id });
    }
  });

  it('with links both ways, takes the one whose source is oldest', () => {
    const demo = { id: '6b00e14ba8567e9848578ba1', tag: 'demographic_data', type: 'table' };
    const phys = { id: '6b00e14ba8567e9848578ba2', tag: 'physical_features', type: 'table' };
    const both = [
      { source_dc_id: phys.id, target_dc_id: demo.id },
      { source_dc_id: demo.id, target_dc_id: phys.id },
    ];
    for (const links of [both, [...both].reverse()]) {
      expect(defaultJoinSelection([phys, demo], links)).toMatchObject({
        leftId: demo.id,
        rightId: phys.id,
      });
    }
    // One link only: its source goes on the left, even the newer table.
    expect(defaultJoinSelection([demo, phys], [both[0]])).toMatchObject({
      leftId: phys.id,
      rightId: demo.id,
    });
  });

  it('excludes the left table from the right options', () => {
    expect(rightTableOptions(joinableTables(dcs), '1').map((d) => d.id)).toEqual(['3']);
  });
});

describe('effectiveOnColumns', () => {
  const preview = {
    on_columns: ['individual_id'],
    suggested_on_columns: ['individual_id'],
    shared_columns: ['individual_id', 'year'],
  };

  it('uses the server suggestion as the initial value', () => {
    expect(effectiveOnColumns(null, preview)).toEqual(['individual_id']);
  });

  it('lets the user clear the key: an emptied pick stays empty', () => {
    expect(effectiveOnColumns([], preview)).toEqual([]);
    expect(joinColumnsProblem([])).toBe('Pick at least one column to join on.');
    expect(joinColumnsProblem(['year'])).toBeNull();
  });

  it('keeps the picked columns that both tables share', () => {
    expect(effectiveOnColumns(['year', 'gone'], preview)).toEqual(['year']);
  });

  it('is empty without a preview', () => {
    expect(effectiveOnColumns(null, null)).toEqual([]);
    expect(effectiveOnColumns(['a'], null)).toEqual(['a']);
  });
});

describe('previewSummary', () => {
  it('reads "<left>: N rows · <right>: M rows → joined: K rows · J columns"', () => {
    expect(
      previewSummary({
        left: { tag: 'demographic_data', rows: 223 },
        right: { tag: 'physical_features', rows: 211 },
        joined_rows: 223,
        joined_columns: ['a', 'b', 'c'],
      }),
    ).toBe(
      'demographic_data: 223 rows · physical_features: 211 rows → joined: 223 rows · 3 columns',
    );
  });
});

describe('defaultJoinName', () => {
  it('joins the two tags', () => {
    expect(defaultJoinName('demographic_data', 'physical_features')).toBe(
      'demographic_data_physical_features',
    );
  });

  it('is empty until both tables are known', () => {
    expect(defaultJoinName('a', '')).toBe('');
    expect(defaultJoinName('', 'b')).toBe('');
  });

  it('replaces characters a name cannot hold', () => {
    const name = defaultJoinName('my table.csv', 'other (2)');
    expect(name).toBe('my_table_csv_other_2');
    expect(isValidJoinName(name)).toBe(true);
  });

  it('is shortened to 100 characters and stays valid', () => {
    const name = defaultJoinName('a'.repeat(80), 'b'.repeat(80));
    expect(name.length).toBeLessThanOrEqual(JOIN_NAME_MAX);
    expect(isValidJoinName(name)).toBe(true);
    expect(name.startsWith('aaa')).toBe(true);
    expect(name.endsWith('bbb')).toBe(true);
  });

  it('does not collide with a join name or a joined_<name> table', () => {
    expect(defaultJoinName('a', 'b', { joinNames: ['a_b'] })).toBe('a_b_2');
    expect(defaultJoinName('a', 'b', { tags: ['joined_a_b'] })).toBe('a_b_2');
    expect(
      defaultJoinName('a', 'b', { joinNames: ['A_B'], tags: ['joined_a_b_2'] }),
    ).toBe('a_b_3');
    // a plain table tagged like the name is no collision: only joined_<name> is
    expect(defaultJoinName('a', 'b', { tags: ['a_b'] })).toBe('a_b');
  });

  it('keeps a suffixed name within 100 characters', () => {
    const base = defaultJoinName('a'.repeat(80), 'b'.repeat(80));
    const next = defaultJoinName('a'.repeat(80), 'b'.repeat(80), { joinNames: [base] });
    expect(next).not.toBe(base);
    expect(next.length).toBeLessThanOrEqual(JOIN_NAME_MAX);
    expect(next.endsWith('_2')).toBe(true);
  });
});

describe('readableApiError', () => {
  it('reads a string detail from the error', () => {
    expect(readableApiError({ detail: 'Join(s) X read this table: delete them first.' })).toBe(
      'Join(s) X read this table: delete them first.',
    );
  });

  it('reads {code, message}', () => {
    expect(readableApiError({ detail: { code: 'name_taken', message: 'Name in use.' } })).toBe(
      'Name in use.',
    );
  });

  it('reads a FastAPI validation list', () => {
    expect(
      readableApiError({
        detail: [
          { loc: ['body', 'name'], msg: 'String should have at most 100 characters' },
          { loc: ['body', 'how'], msg: 'Value error, bad type' },
        ],
      }),
    ).toBe('String should have at most 100 characters; bad type');
  });

  it('reads the raw body kept in an error message', () => {
    expect(
      readableApiError(
        new Error('Failed: 409 {"detail":"Join(s) penguins read this table: delete them first."}'),
      ),
    ).toBe('Join(s) penguins read this table: delete them first.');
    expect(
      readableApiError(new Error('422 {"detail":[{"loc":["body"],"msg":"Field required"}]}')),
    ).toBe('Field required');
    expect(readableApiError(new Error('{"detail":{"code":"x","message":"Readable."}}'))).toBe(
      'Readable.',
    );
  });

  it('passes a plain message or string through', () => {
    expect(readableApiError(new Error('Network down'))).toBe('Network down');
    expect(readableApiError('Oops')).toBe('Oops');
  });

  it('falls back when nothing is readable', () => {
    expect(readableApiError(undefined, 'Nope')).toBe('Nope');
    expect(readableApiError(new Error(''), 'Nope')).toBe('Nope');
    expect(readableApiError({ detail: [] }, 'Nope')).toBe('Nope');
  });
});

describe('joinRebuildNotice', () => {
  it('keeps the message when no join reads the table', () => {
    expect(joinRebuildNotice('Data replaced.', [])).toEqual({
      color: null,
      message: 'Data replaced.',
    });
    expect(joinRebuildNotice('Data replaced.', undefined).color).toBeNull();
    expect(joinRebuildNotice('Data replaced.', [{ join: 'p', status: 'unchanged' }]).message).toBe(
      'Data replaced.',
    );
  });

  it('says a rebuilt join was updated', () => {
    expect(joinRebuildNotice('Data replaced', [{ join: 'penguins', status: 'rebuilt' }])).toEqual({
      color: null,
      message: "Data replaced. Join 'penguins' updated.",
    });
  });

  it('warns about a join that could not be rebuilt', () => {
    expect(
      joinRebuildNotice('Data replaced.', [
        { join: 'penguins', status: 'failed', error: 'No shared column.' },
      ]),
    ).toEqual({
      color: 'yellow',
      message: "Data replaced, but join 'penguins' could not be rebuilt: No shared column.",
    });
  });

  it('names every failed join', () => {
    const n = joinRebuildNotice('Saved 2 cells.', [
      { join: 'a', status: 'failed', error: 'x' },
      { join: 'b', status: 'rebuilt' },
      { join: 'c', status: 'failed' },
    ]);
    expect(n.color).toBe('yellow');
    expect(n.message).toBe("Saved 2 cells, but 2 joins could not be rebuilt: 'a' (x), 'c'");
  });
});

describe('dependent joins', () => {
  const joins = [
    { name: 'penguins', left_dc_id: 'a', right_dc_id: 'b', result_tag: 'joined_penguins' },
    { name: 'other', left_dc_id: 'c', right_dc_id: 'a', result_tag: 'joined_other' },
    { name: 'far', left_dc_id: 'c', right_dc_id: 'd', result_tag: 'joined_far' },
  ];

  it('finds the joins reading a table on either side', () => {
    expect(joinsReadingTable(joins, 'a').map((j) => j.name)).toEqual(['penguins', 'other']);
    expect(joinsReadingTable(joins, 'b').map((j) => j.name)).toEqual(['penguins']);
    expect(joinsReadingTable(joins, 'zzz')).toEqual([]);
  });

  it('warns before clearing', () => {
    expect(clearJoinsWarning([joins[0]])).toBe(
      "Join 'penguins' reads this table: after clearing, joined_penguins is rebuilt with this side empty.",
    );
    expect(clearJoinsWarning(joins.slice(0, 2))).toContain("Joins 'penguins', 'other' read");
    expect(clearJoinsWarning([])).toBeNull();
  });

  it('blocks a delete', () => {
    expect(deleteJoinsBlock([joins[0]])).toBe(
      "Join 'penguins' reads this table: delete the join first.",
    );
    expect(deleteJoinsBlock(joins.slice(0, 2))).toBe(
      "Joins 'penguins', 'other' read this table: delete the joins first.",
    );
    expect(deleteJoinsBlock([])).toBeNull();
  });
});

describe('joinDashboardsSentence', () => {
  it('lists the dashboards using the joined table', () => {
    expect(
      joinDashboardsSentence('joined_penguins', [{ title: 'A' }, { title: 'B' }]),
    ).toBe(
      'Used by 2 dashboards: A, B. Their components on joined_penguins will show an error until a join of the same name is created again.',
    );
    expect(joinDashboardsSentence('joined_penguins', [{ title: 'A' }])).toMatch(
      /^Used by 1 dashboard: A\. Its components on joined_penguins/,
    );
  });

  it('is null when no dashboard uses it', () => {
    expect(joinDashboardsSentence('joined_penguins', [])).toBeNull();
    expect(joinDashboardsSentence('joined_penguins', undefined)).toBeNull();
  });
});

describe('deleteJoinedTableNotice', () => {
  const joins = [
    { name: 'penguins', result_dc_id: 'j1' },
    { name: 'other', result_dc_id: null },
  ];
  it('says the join producing the table goes with it', () => {
    expect(deleteJoinedTableNotice(joins, 'j1')).toBe(
      "This is the table of join 'penguins': the join is deleted too. Its sources stay.",
    );
  });
  it('says nothing for a table no join produces', () => {
    expect(deleteJoinedTableNotice(joins, 'a')).toBeNull();
    expect(deleteJoinedTableNotice([], 'j1')).toBeNull();
  });
});

describe('joinRebuildNotice after a failed rebuild', () => {
  it('says the join is back even when its rows did not change', () => {
    const notice = joinRebuildNotice('Data replaced (10 rows).', [
      { join: 'penguins', status: 'unchanged', recovered: true },
    ]);
    expect(notice).toEqual({
      color: null,
      message: "Data replaced (10 rows). Join 'penguins' updated.",
    });
  });
  it('stays quiet for an unchanged join that had not failed', () => {
    expect(
      joinRebuildNotice('Data replaced (10 rows).', [{ join: 'penguins', status: 'unchanged' }])
        .message,
    ).toBe('Data replaced (10 rows).');
  });
});
