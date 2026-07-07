/** UTF-8-safe base64 for GitHub blob content (btoa alone breaks on non-ASCII). */
export function encodeBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}
