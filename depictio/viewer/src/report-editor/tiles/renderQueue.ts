/**
 * A tiny queue that lets only a few live tiles render at once: each one fires
 * its own data requests and a Plotly draw, and a section of thirty would
 * otherwise start all of them in the same second.
 */
export const MAX_IN_FLIGHT = 3;

type Grant = (release: () => void) => void;

let active = 0;
const waiting: Grant[] = [];

function pump(): void {
  while (active < MAX_IN_FLIGHT && waiting.length > 0) {
    const grant = waiting.shift() as Grant;
    active += 1;
    let released = false;
    grant(() => {
      if (released) return;
      released = true;
      active -= 1;
      pump();
    });
  }
}

/** Ask for a render slot. `onGrant` receives the function that frees it (call
 *  it once the tile is drawn, failed or abandoned; calling twice is harmless).
 *  The returned function withdraws a request still waiting. */
export function requestRenderSlot(onGrant: Grant): () => void {
  waiting.push(onGrant);
  pump();
  return () => {
    const i = waiting.indexOf(onGrant);
    if (i >= 0) waiting.splice(i, 1);
  };
}
