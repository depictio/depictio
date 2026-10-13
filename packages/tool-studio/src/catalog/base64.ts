/** UTF-8-safe base64 for GitHub blob content (btoa alone breaks on non-ASCII). */
export function encodeBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

/** Inverse of {@link encodeBase64}. The GitHub contents API returns base64 with
 *  embedded newlines, which `atob` rejects — strip whitespace first. */
export function decodeBase64(b64: string): string {
  const binary = atob(b64.replace(/\s+/g, ''));
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}
