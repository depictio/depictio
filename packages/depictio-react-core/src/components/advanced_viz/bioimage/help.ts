// The tile's "How to use" guide: one short entry per thing the reader can do
// with *this* image. A topic that does not apply (no Z axis, no cells, no
// labels) is left out, so the guide never explains a control that is absent.

import { MAX_RENDERED_CHANNELS } from './channels';

export interface HelpContext {
  /** More than one sample to pick from. */
  samples: boolean;
  /** The sample follows a dashboard filter rather than the picker. */
  sampleFollowsFilter: boolean;
  /** An HCS plate: a well to pick. */
  plate: boolean;
  hasZ: boolean;
  hasT: boolean;
  channels: number;
  /** Cells drawn as points over the image. */
  points: boolean;
  /** The column the points are coloured by, if any. */
  colourBy?: string | null;
  /** Points follow the shown plane (z_col / t_col). */
  pointsFollowPlane: boolean;
  /** Lasso / rectangle selection filters the dashboard. */
  selectable: boolean;
  labels: boolean;
  /** Processing steps to step through (raw, rigid, affine...). */
  steps?: boolean;
  /** A reference image (the fixed image) to compare a step against. */
  reference?: boolean;
  /** Another image laid over this one, in its own channels (e.g. LM over EM). */
  overlay?: boolean;
}

export interface HelpTopic {
  key: string;
  title: string;
  text: string;
}

export function helpTopics(ctx: HelpContext): HelpTopic[] {
  const out: HelpTopic[] = [
    {
      key: 'move',
      title: 'Move around',
      text: 'Drag to pan; scroll or pinch to zoom. The target button at the top right resets the view.',
    },
  ];
  if (ctx.samples || ctx.plate) {
    const what = ctx.plate && ctx.samples ? 'sample and well' : ctx.plate ? 'well' : 'sample';
    out.push({
      key: 'pick',
      title: ctx.plate ? 'Pick a well' : 'Pick a sample',
      text:
        `Choose the ${what} in the controls. ` +
        (ctx.sampleFollowsFilter
          ? 'Here a dashboard filter decides: change the filter and the image follows.'
          : 'A dashboard filter on the same column picks it too.'),
    });
  }
  if (ctx.steps) {
    out.push({
      key: 'steps',
      title: 'Processing steps',
      text:
        'Step picks which stage of the processing is shown, the last one first; its metrics, ' +
        'and how they moved since the step before, sit under it.' +
        (ctx.reference
          ? ' Compare lays the reference image over it: Colours draws the step in green and the ' +
            'reference in magenta, so what lines up turns grey-white and an offset shows as ' +
            'coloured fringes; Fade blends the reference in with the slider.'
          : ''),
    });
  }
  if (ctx.hasZ || ctx.hasT) {
    const parts = [
      ctx.hasZ ? 'Z moves through the stack, one plane at a time' : null,
      ctx.hasT ? 'Time steps through the time points, and play runs them' : null,
    ].filter(Boolean);
    out.push({
      key: 'planes',
      title: 'Planes',
      text: `${parts.join('; ')}. The tile shows one 2D plane; for the volume in 3D, open it in Neuroglancer.`,
    });
  }
  if (ctx.channels > 0) {
    out.push({
      key: 'channels',
      title: 'Channels',
      text:
        'Tick a channel to show it' +
        (ctx.channels > MAX_RENDERED_CHANNELS ? ` (at most ${MAX_RENDERED_CHANNELS} at once)` : '') +
        '; the swatch next to it changes its colour. The slider is the contrast window: ' +
        'values left of it are black, values right of it full colour. Narrow it to bring out faint signal.',
    });
  }
  if (ctx.overlay) {
    out.push({
      key: 'overlay',
      title: 'Overlay',
      text:
        'A second image, registered onto this one, is drawn over it in its own colours. The ' +
        'Overlay slider fades it (left hides it); its channels, under Overlay in the settings, ' +
        'switch and contrast like the image\'s own. It covers the same field, so it follows ' +
        'zoom, pan and Z, at its own, often coarser, resolution.',
    });
  }
  if (ctx.points) {
    out.push({
      key: 'cells',
      title: 'Cells',
      text:
        'Each dot is a cell from the table' +
        (ctx.colourBy ? `, coloured by ${ctx.colourBy} (the key under the image)` : '') +
        '.' +
        (ctx.pointsFollowPlane
          ? ' Only the cells of the shown plane are drawn; "All planes" draws them all.'
          : '') +
        ' Filters elsewhere on the dashboard fade the cells they leave out.',
    });
  }
  if (ctx.selectable) {
    out.push({
      key: 'select',
      title: 'Select cells',
      text:
        'Switch the pointer from pan to lasso or rectangle and draw around cells: the selection ' +
        'filters the rest of the dashboard. The × on the "selected" badge clears it.',
    });
  }
  if (ctx.labels) {
    out.push({
      key: 'labels',
      title: 'Labels',
      text:
        'Segmentation masks drawn over the image, one colour per object. Outlines show the image ' +
        'under them; the opacity slider fades the fill.',
    });
  }
  out.push(
    {
      key: 'badges',
      title: 'Badges',
      text:
        'Above the image: the file format, the OME-NGFF version with its check (green: valid; ' +
        'orange: hover to read what is off) and the axes (T time, C channels, Z depth, Y and X the plane).',
    },
    {
      key: 'open',
      title: 'Go further',
      text:
        'The arrow button opens the store in vizarr, Neuroglancer, Vitessce or the NGFF validator: ' +
        '3D, every channel at once, a whole plate.',
    },
  );
  return out;
}
