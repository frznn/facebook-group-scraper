from dataclasses import dataclass, field


AUTHOR_METADATA_PREFIX = "Author: "
DATE_METADATA_PREFIX = "Date: "
SUPPORTED_OUTPUT_FORMATS = ("text", "markdown")
OUTPUT_FORMAT_ALIASES = {
    "txt": "text",
    "md": "markdown",
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


def render_output(posts, output_format):
    renderers = {
        "text": render_text,
        "markdown": render_markdown,
    }
    return renderers[output_format](posts)
