from dataclasses import dataclass, field


AUTHOR_METADATA_PREFIX = "Author: "
DATE_METADATA_PREFIX = "Date: "
SUPPORTED_OUTPUT_FORMATS = ("text",)
OUTPUT_FORMAT_ALIASES = {
    "txt": "text",
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


def render_output(posts, output_format):
    if output_format == "text":
        return render_text(posts)
    raise ValueError(f"Unsupported OUTPUT_FORMAT '{output_format}'")
