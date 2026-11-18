/** A raw sample as the recipe engine takes it. `.gz` files are decompressed
 *  here (the engine writes text), and keep their own name as `sourcePath` so a
 *  source glob such as `*.per-base.bed.gz` still matches them. */
export async function readRawSample(f: File): Promise<{ fileName: string; text: string; sourcePath?: string }> {
  if (!/\.gz$/i.test(f.name)) return { fileName: f.name, text: await f.text() };
  const text = await new Response(f.stream().pipeThrough(new DecompressionStream('gzip'))).text();
  return { fileName: f.name.replace(/\.gz$/i, ''), text, sourcePath: f.name };
}
