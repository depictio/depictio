/**
 * SSE frame parsing, kept free of imports so it is unit-tested in node.
 * The /ai routes frame every event as `event: <type>\ndata: <json>\n\n`.
 */

/** One parsed SSE frame, before its payload is typed. */
export interface SSEFrame {
  type: string;
  data: Record<string, unknown>;
}

/** Split a buffer of SSE text into complete frames and the unfinished rest.
 *  Frames end on a blank line; CRLF line endings are normalised first so a
 *  proxy that rewrites them does not stall the stream. Frames without an
 *  `event:` line are dropped. */
export function splitSSEFrames(buffer: string): { frames: SSEFrame[]; rest: string } {
  const text = buffer.replace(/\r\n/g, '\n');
  const frames: SSEFrame[] = [];
  let rest = text;
  let sep = rest.indexOf('\n\n');
  while (sep !== -1) {
    const parsed = parseSSEFrame(rest.slice(0, sep));
    if (parsed) frames.push(parsed);
    rest = rest.slice(sep + 2);
    sep = rest.indexOf('\n\n');
  }
  return { frames, rest };
}

/** Parse one SSE frame (the lines between two blank lines). Other SSE
 *  fields (id:, retry:) are ignored; a payload that is not JSON is kept
 *  under `raw`. */
export function parseSSEFrame(frame: string): SSEFrame | null {
  let eventName: string | null = null;
  const dataLines: string[] = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (!eventName) return null;
  let data: Record<string, unknown> = {};
  if (dataLines.length) {
    try {
      data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>;
    } catch {
      data = { raw: dataLines.join('\n') };
    }
  }
  return { type: eventName, data };
}
