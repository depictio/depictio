import { describe, expect, it } from 'vitest';

import { parseSSEFrame, splitSSEFrames } from './sse';

describe('parseSSEFrame', () => {
  it('reads the event name and JSON payload', () => {
    expect(parseSSEFrame('event: finding\ndata: {"title":"x"}')).toEqual({
      type: 'finding',
      data: { title: 'x' },
    });
  });

  it('joins multi-line data and ignores id/retry fields', () => {
    expect(parseSSEFrame('id: 3\nevent: budget\nretry: 10\ndata: {"a":\ndata: 1}')).toEqual({
      type: 'budget',
      data: { a: 1 },
    });
  });

  it('keeps a non-JSON payload under raw', () => {
    expect(parseSSEFrame('event: status\ndata: hello')).toEqual({
      type: 'status',
      data: { raw: 'hello' },
    });
  });

  it('drops a frame without an event line', () => {
    expect(parseSSEFrame('data: {}')).toBeNull();
  });

  it('gives an empty payload to an event without data', () => {
    expect(parseSSEFrame('event: done')).toEqual({ type: 'done', data: {} });
  });
});

describe('splitSSEFrames', () => {
  it('returns complete frames and keeps the unfinished tail', () => {
    const { frames, rest } = splitSSEFrames(
      'event: run_started\ndata: {"run_id":"r1"}\n\nevent: agent_started\ndata: {"agent',
    );
    expect(frames).toEqual([{ type: 'run_started', data: { run_id: 'r1' } }]);
    expect(rest).toBe('event: agent_started\ndata: {"agent');
  });

  it('reassembles a frame split across chunks', () => {
    const first = splitSSEFrames('event: done\nda');
    expect(first.frames).toEqual([]);
    const second = splitSSEFrames(`${first.rest}ta: {}\n\n`);
    expect(second.frames).toEqual([{ type: 'done', data: {} }]);
    expect(second.rest).toBe('');
  });

  it('normalises CRLF line endings, including one split across chunks', () => {
    const first = splitSSEFrames('event: done\r\ndata: {}\r');
    expect(first.frames).toEqual([]);
    const second = splitSSEFrames(`${first.rest}\n\r\n`);
    expect(second.frames).toEqual([{ type: 'done', data: {} }]);
  });

  it('parses several frames from one chunk', () => {
    const { frames } = splitSSEFrames('event: a\ndata: {}\n\nevent: b\ndata: {}\n\n');
    expect(frames.map((f) => f.type)).toEqual(['a', 'b']);
  });
});
