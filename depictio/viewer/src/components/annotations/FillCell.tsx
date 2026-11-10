import React from 'react';
import type { ICellRendererParams } from 'ag-grid-community';

/** What the panel gives a fillable column: write the focused cell's value into
 *  every row between `from` and `to` (display indexes). */
export interface FillParams {
  onFill: (colId: string, from: number, to: number) => void;
}

const PREVIEW_CLASS = 'dc-fill-preview';

/** The cells of one column between two display indexes, as DOM nodes. */
function cellsBetween(root: HTMLElement, colId: string, a: number, b: number): HTMLElement[] {
  const [lo, hi] = a < b ? [a, b] : [b, a];
  const out: HTMLElement[] = [];
  root
    .querySelectorAll<HTMLElement>(`.ag-row .ag-cell[col-id="${CSS.escape(colId)}"]`)
    .forEach((cell) => {
      const index = Number(cell.closest('.ag-row')?.getAttribute('row-index'));
      if (index >= lo && index <= hi) out.push(cell);
    });
  return out;
}

/**
 * A cell that shows its value and, while it is the focused one, a small
 * square in its corner: drag it down (or up) to copy the value into the cells
 * it crosses, as a spreadsheet's fill handle does. AG Grid Community has no
 * fill, so the drag is followed here, by the row under the pointer.
 */
const FillCell: React.FC<ICellRendererParams & FillParams> = (params) => {
  const text = params.valueFormatted ?? params.value;
  const colId = params.column?.getColId() ?? '';

  const start = (event: React.MouseEvent) => {
    // The cell must not open its editor, and the grid must not start a selection.
    event.preventDefault();
    event.stopPropagation();
    const from = params.node.rowIndex;
    if (from === null || !colId) return;
    const grid = (event.currentTarget as HTMLElement).closest<HTMLElement>('.ag-root-wrapper');
    if (!grid) return;
    let to = from;
    const clear = () => grid.querySelectorAll(`.${PREVIEW_CLASS}`).forEach((n) => n.classList.remove(PREVIEW_CLASS));
    const move = (e: MouseEvent) => {
      const row = document.elementFromPoint(e.clientX, e.clientY)?.closest('.ag-row');
      const index = row ? Number(row.getAttribute('row-index')) : NaN;
      if (Number.isNaN(index) || index === to) return;
      to = index;
      clear();
      if (to !== from) cellsBetween(grid, colId, from, to).forEach((c) => c.classList.add(PREVIEW_CLASS));
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      clear();
      if (to !== from) params.onFill(colId, from, to);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  return (
    <>
      <span className="dc-fill-text">{text === null || text === undefined ? '' : String(text)}</span>
      <span
        className="dc-fill-handle"
        role="presentation"
        title="Drag to copy this value into the cells below"
        data-testid="fill-handle"
        onMouseDown={start}
        onClick={(e) => e.stopPropagation()}
        onDoubleClick={(e) => e.stopPropagation()}
      />
    </>
  );
};

export default FillCell;
