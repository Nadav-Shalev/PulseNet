"""Rich text for PulseNet: Markdown to HTML, the HTML allowlist, and HTML to text.

    body_html = sanitize_html(to_html(markdown_text))   # safe to store and render
    text = html_to_text(body_html)                      # what readers see, as text

Like llm/ and moderation.py, this module imports neither Flask nor the app: app.py
uses it for every post and comment, and the agents (backend/agents/) write their
posts and comments through the same functions from their own process.
"""

import html as _html
import re
from html.parser import HTMLParser

try:
    import markdown as _md
    def to_html(text):
        return _md.markdown(text)
except ImportError:
    def to_html(text):
        paragraphs = text.split('\n\n')
        return ''.join(
            f'<p>{_html.escape(p.strip())}</p>'
            for p in paragraphs if p.strip()
        )


# ─── Rich-text sanitization (user-submitted HTML from the WYSIWYG editor) ──────
# Whitelist only the formatting the editor can produce. bleach strips everything
# else (including <script>, event handlers, and javascript: URLs) so stored HTML
# is safe to render with dangerouslySetInnerHTML.
ALLOWED_TAGS = [
    "p", "br", "span", "strong", "em", "b", "i", "u", "s",
    "a", "ul", "ol", "li", "blockquote", "h1", "h2", "h3", "pre", "code",
]
ALLOWED_ATTRS = {"a": ["href", "title", "target", "rel"], "*": ["class"]}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def _rel_tokens_with_blank_target_safety(rel_value):
    tokens = (rel_value or "").split()
    seen = {token.lower() for token in tokens}
    for required in ("noopener", "noreferrer"):
        if required not in seen:
            tokens.append(required)
            seen.add(required)
    return " ".join(tokens)


def _add_rel_to_anchor_start_tag(start_tag, rel_value):
    safe_rel = _html.escape(_rel_tokens_with_blank_target_safety(rel_value), quote=True)
    if rel_value is None:
        insert_at = start_tag.rfind("/>") if start_tag.rstrip().endswith("/>") else start_tag.rfind(">")
        if insert_at == -1:
            return start_tag
        return f'{start_tag[:insert_at]} rel="{safe_rel}"{start_tag[insert_at:]}'

    return re.sub(
        r'(\srel\s*=\s*)(["\'])(.*?)\2',
        lambda match: f"{match.group(1)}{match.group(2)}{safe_rel}{match.group(2)}",
        start_tag,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )


class _BlankTargetRelParser(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.offset = 0
        self.replacements = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return

        attr_map = {name.lower(): value for name, value in attrs if name}
        target = (attr_map.get("target") or "").strip().lower()
        if target != "_blank":
            return

        start_tag = self.get_starttag_text()
        if not start_tag:
            return

        start = self.html.find(start_tag, self.offset)
        if start == -1:
            return

        self.offset = start + len(start_tag)
        updated = _add_rel_to_anchor_start_tag(start_tag, attr_map.get("rel"))
        if updated != start_tag:
            self.replacements.append((start, self.offset, updated))


def _ensure_blank_target_rel(clean_html):
    """Add noopener/noreferrer only to sanitized <a target="_blank"> start tags."""
    parser = _BlankTargetRelParser(clean_html)
    parser.feed(clean_html)
    if not parser.replacements:
        return clean_html

    pieces = []
    cursor = 0
    for start, end, replacement in parser.replacements:
        pieces.append(clean_html[cursor:start])
        pieces.append(replacement)
        cursor = end
    pieces.append(clean_html[cursor:])
    return "".join(pieces)

try:
    import bleach
    def sanitize_html(raw):
        clean = bleach.clean(
            raw or "",
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            protocols=ALLOWED_PROTOCOLS,
            strip=True,
        )
        return _ensure_blank_target_rel(clean)
except ImportError:
    # bleach missing → safest possible fallback: escape everything (no rich text,
    # but no XSS either). Install bleach (requirements.txt) to enable formatting.
    def sanitize_html(raw):
        return _html.escape(raw or "")


def html_to_text(html):
    """Plain-text excerpt from HTML for the card preview / description column.

    bleach (via html5lib) re-serializes a non-breaking space back to the literal
    "&nbsp;" entity, and editors like Quill emit &nbsp; for spaces — so we unescape
    HTML entities and normalize NBSP to a regular space to get clean plain text."""
    try:
        import bleach
        text = bleach.clean(html or "", tags=[], strip=True)
    except ImportError:
        text = re.sub(r"<[^>]+>", "", html or "")
    return _html.unescape(text).replace("\xa0", " ").strip()
