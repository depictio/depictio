/**
 * The report's rich text, as HTML for the live preview frame.
 *
 * The introduction and the conclusion are stored as TipTap JSON. The preview
 * frame shows them as HTML, so the page converts with the same extensions the
 * editor field uses, then runs the result through an allow-list: the frame is
 * sandboxed, but its text should still be only what the editor can produce.
 */
import { Link } from '@mantine/tiptap';
import { generateHTML } from '@tiptap/react';
import type { Extensions } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import type { ReportDoc } from 'depictio-react-core';

import { isEmptyDoc } from './model';

/** The extensions of the introduction and conclusion fields. */
export const DOC_EXTENSIONS: Extensions = [StarterKit, Link.configure({ openOnClick: false })];

const ALLOWED_TAGS = new Set([
  'p', 'br', 'strong', 'b', 'em', 'i', 's', 'u', 'code', 'pre', 'blockquote', 'hr',
  'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'span',
]);
const SAFE_HREF = /^(https?:|mailto:|#|\/)/i;

function clean(node: Element): void {
  for (const child of Array.from(node.children)) {
    if (!ALLOWED_TAGS.has(child.tagName.toLowerCase())) {
      // Unknown element: keep its text, drop the markup.
      child.replaceWith(...Array.from(child.childNodes));
      continue;
    }
    for (const attr of Array.from(child.attributes)) {
      const name = attr.name.toLowerCase();
      const keep =
        child.tagName === 'A' &&
        (name === 'href' ? SAFE_HREF.test(attr.value.trim()) : name === 'rel' || name === 'target');
      if (!keep) child.removeAttribute(attr.name);
    }
    clean(child);
  }
}

/** Keep only the tags and attributes a rich-text field can produce. */
export function sanitizeHtml(html: string): string {
  const body = new DOMParser().parseFromString(html, 'text/html').body;
  body.querySelectorAll('script, style, iframe, object, embed').forEach((el) => el.remove());
  clean(body);
  return body.innerHTML;
}

/** A stored document as safe HTML; '' when it holds no text or cannot be read. */
export function docToHtml(doc: ReportDoc | null): string {
  if (isEmptyDoc(doc)) return '';
  try {
    return sanitizeHtml(generateHTML(doc as Parameters<typeof generateHTML>[0], DOC_EXTENSIONS));
  } catch {
    return '';
  }
}
