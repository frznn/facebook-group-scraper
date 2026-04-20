from html import escape
import json
from dataclasses import dataclass, field
from dataclasses import asdict


AUTHOR_METADATA_PREFIX = "Author: "
DATE_METADATA_PREFIX = "Date: "


SUPPORTED_OUTPUT_FORMATS = ("text", "markdown", "html", "json", "jsonl")
OUTPUT_FORMAT_ALIASES = {
    "txt": "text",
    "md": "markdown",
    "htm": "html",
    "ndjson": "jsonl",
}


@dataclass
class ExternalLink:
    url: str
    title: str | None = None


@dataclass
class ScrapedPost:
    author: str | None = None
    date: str | None = None
    message: str = ""
    external_links: list[ExternalLink] = field(default_factory=list)


def normalize_output_format(output_format):
    normalized = OUTPUT_FORMAT_ALIASES.get(output_format.strip().lower(), output_format.strip().lower())
    if normalized not in SUPPORTED_OUTPUT_FORMATS:
        supported = ", ".join(SUPPORTED_OUTPUT_FORMATS)
        raise ValueError(f"Unsupported OUTPUT_FORMAT '{output_format}'. Supported formats: {supported}")
    return normalized


def escape_markdown_text(text):
    escaped = text.replace("\\", "\\\\")
    for char in ("*", "_", "[", "]", "`"):
        escaped = escaped.replace(char, f"\\{char}")
    return escaped


def render_external_links_text(external_links):
    separator = "\n\n" if any(link.title for link in external_links) else "\n"
    rendered_links = []
    for link in external_links:
        if link.title:
            rendered_links.append(f"{link.title}\n{link.url}")
        else:
            rendered_links.append(link.url)
    return separator.join(rendered_links)


def render_external_link_urls(external_links):
    return "\n".join(link.url for link in external_links)


def post_identity_text(post):
    parts = []
    if post.message:
        parts.append(post.message)
    if post.external_links:
        parts.append(render_external_links_text(post.external_links))
    return "\n\n".join(parts).strip()


def render_text_body(post):
    parts = []
    if post.author:
        parts.append(f"{AUTHOR_METADATA_PREFIX}{post.author}")
    if post.date:
        parts.append(f"{DATE_METADATA_PREFIX}{post.date}")
    if post.message:
        parts.append(post.message)
    if post.external_links:
        parts.append(render_external_links_text(post.external_links))
    return "\n\n".join(parts).strip()


def render_text(posts):
    blocks = [f"--- POST {index} ---\n{render_text_body(post)}" for index, post in enumerate(posts, 1)]
    return "\n\n".join(blocks).rstrip() + "\n"


def render_external_links_markdown(external_links):
    separator = "\n\n" if any(link.title for link in external_links) else "\n"
    rendered_links = []
    for link in external_links:
        if link.title:
            rendered_links.append(f"[{escape_markdown_text(link.title)}](<{link.url}>)")
        else:
            rendered_links.append(f"<{link.url}>")
    return separator.join(rendered_links)


def render_markdown(posts):
    lines = ["# Facebook Group Scrape", "", f"{len(posts)} posts captured.", ""]

    for index, post in enumerate(posts, 1):
        lines.append(f"## Post {index}")
        lines.append("")

        if post.author:
            lines.append(f"**Author:** {escape_markdown_text(post.author)}")
        if post.date:
            lines.append(f"**Date:** {escape_markdown_text(post.date)}")
        if post.author or post.date:
            lines.append("")

        if post.message:
            lines.append(post.message)
            lines.append("")

        if post.external_links:
            lines.append(render_external_links_markdown(post.external_links))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_html(posts):
    cards = []
    nav_links = []

    for index, post in enumerate(posts, 1):
        nav_links.append(f'<a href="#post-{index}">#{index}</a>')

        metadata = []
        if post.author:
            metadata.append(
                f'<span class="meta-pill"><span class="meta-label">Author</span>{escape(post.author)}</span>'
            )
        if post.date:
            metadata.append(
                f'<span class="meta-pill"><span class="meta-label">Date</span>{escape(post.date)}</span>'
            )

        message_html = ""
        if post.message:
            paragraphs = []
            for paragraph in post.message.split("\n\n"):
                escaped = escape(paragraph).replace("\n", "<br>\n")
                paragraphs.append(f"<p>{escaped}</p>")
            message_html = f'<div class="post-message">{"".join(paragraphs)}</div>'

        links_html = ""
        if post.external_links:
            items = []
            for link in post.external_links:
                label = escape(link.title or link.url)
                items.append(
                    f'<li><a href="{escape(link.url, quote=True)}" target="_blank" rel="noopener noreferrer">{label}</a></li>'
                )
            links_html = f'<ul class="post-links">{"".join(items)}</ul>'

        cards.append(
            "\n".join(
                [
                    f'<article class="post-card" id="post-{index}">',
                    f'  <h2 class="post-title">Post {index}</h2>',
                    f'  <div class="post-meta">{"".join(metadata)}</div>' if metadata else "",
                    f"  {message_html}" if message_html else "",
                    f"  {links_html}" if links_html else "",
                    "</article>",
                ]
            )
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Facebook Group Scrape</title>
  <style>
    :root {{
      --bg: #f4efe6;
      --surface: #fffdf8;
      --surface-strong: #f0e3cd;
      --text: #1d1b18;
      --muted: #6a6258;
      --line: #d9ccb7;
      --accent: #8b3a2b;
      --accent-soft: #f6d9c6;
      --shadow: 0 16px 50px rgba(85, 64, 39, 0.12);
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      background:
        radial-gradient(circle at top, rgba(139, 58, 43, 0.08), transparent 28rem),
        linear-gradient(180deg, #fbf7ef 0%, var(--bg) 100%);
      color: var(--text);
      font: 16px/1.6 Georgia, "Times New Roman", serif;
    }}

    main {{
      width: min(1100px, calc(100vw - 2rem));
      margin: 0 auto;
      padding: 2.5rem 0 4rem;
    }}

    .page-header {{
      margin-bottom: 1.5rem;
    }}

    h1 {{
      margin: 0;
      font-size: clamp(2rem, 4vw, 3.25rem);
      line-height: 1.05;
      letter-spacing: -0.03em;
    }}

    .subtitle {{
      margin: 0.75rem 0 0;
      color: var(--muted);
    }}

    .post-nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin: 1.5rem 0 2rem;
    }}

    .post-nav a,
    .post-links a {{
      color: var(--accent);
      text-decoration: none;
    }}

    .post-nav a {{
      padding: 0.3rem 0.7rem;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 253, 248, 0.82);
    }}

    .posts {{
      display: grid;
      gap: 1rem;
    }}

    .post-card {{
      padding: 1.4rem 1.4rem 1.2rem;
      border: 1px solid var(--line);
      border-radius: 22px;
      background: color-mix(in srgb, var(--surface) 92%, white 8%);
      box-shadow: var(--shadow);
    }}

    .post-title {{
      margin: 0 0 0.8rem;
      font-size: 1.3rem;
    }}

    .post-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.55rem;
      margin-bottom: 1rem;
    }}

    .meta-pill {{
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      padding: 0.32rem 0.7rem;
      border-radius: 999px;
      background: var(--surface-strong);
      color: var(--text);
      font-size: 0.92rem;
    }}

    .meta-label {{
      color: var(--muted);
      text-transform: uppercase;
      font-size: 0.72rem;
      letter-spacing: 0.08em;
    }}

    .post-message p {{
      margin: 0 0 0.95rem;
    }}

    .post-message p:last-child {{
      margin-bottom: 0;
    }}

    .post-links {{
      margin: 1rem 0 0;
      padding-left: 1.25rem;
    }}
  </style>
</head>
<body>
  <main>
    <header class="page-header">
      <h1>Facebook Group Scrape</h1>
      <p class="subtitle">{len(posts)} posts captured.</p>
    </header>
    <nav class="post-nav">{''.join(nav_links)}</nav>
    <section class="posts">
      {''.join(cards)}
    </section>
  </main>
</body>
</html>
"""


def post_to_dict(post, index):
    return {
        "index": index,
        "author": post.author,
        "date": post.date,
        "message": "\n\n".join(
            part
            for part in [post.message, render_external_link_urls(post.external_links)]
            if part
        ).strip(),
        "links": [asdict(link) for link in post.external_links],
    }


def render_json(posts):
    payload = [post_to_dict(post, index) for index, post in enumerate(posts, 1)]
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_jsonl(posts):
    lines = [
        json.dumps(post_to_dict(post, index), ensure_ascii=False)
        for index, post in enumerate(posts, 1)
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_output(posts, output_format):
    renderers = {
        "text": render_text,
        "markdown": render_markdown,
        "html": render_html,
        "json": render_json,
        "jsonl": render_jsonl,
    }
    return renderers[output_format](posts)
