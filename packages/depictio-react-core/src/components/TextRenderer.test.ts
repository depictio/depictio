import { describe, expect, it } from 'vitest';

import { textTitleSize } from './TextRenderer';

describe('textTitleSize', () => {
  it('passes heading names through', () => {
    expect(textTitleSize('h3')).toBe('h3');
  });

  it('maps the t-shirt sizes onto the heading scale, sm to h4', () => {
    expect(textTitleSize('sm')).toBe('h4');
    expect(textTitleSize('xl')).toBe('h1');
  });

  it('returns null for anything else, so the heading level decides', () => {
    expect(textTitleSize(undefined)).toBeNull();
    expect(textTitleSize('huge')).toBeNull();
  });
});
