// Plain text from a comment box -> HTML that shows exactly what was typed.
//
// The API takes HTML (body_html) and sanitizes it, but sanitizing is for safety,
// not fidelity: sent as-is, "use <div>" would lose its tag and "a<b" could turn
// bold. Escaping makes every character literal; line breaks become <br>.
// Quotes are left alone: they only matter inside attributes, and leaving them
// keeps the worst case at 5 characters per typed one ("&" -> "&amp;"), within
// the backend's raw-HTML limit (5 x 2000 = 10000).
const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;' };

export function textToHtml(text) {
  return String(text ?? '')
    .replace(/[&<>]/g, ch => ESCAPES[ch])
    .replace(/\r?\n/g, '<br>');
}
