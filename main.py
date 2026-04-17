import re
import time
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlunparse

from playwright.sync_api import sync_playwright

MAX_POSTS = 50
# Set MAX_POSTS to None to scrape all posts that the feed can still load.
# ⚠️ THAY ĐỔI URL NÀY THÀNH URL NHÓM FACEBOOK CỦA BẠN
GROUP_URL = "https://www.facebook.com/groups/YOUR_GROUP_ID_HERE"
OUTPUT_FILE = "fb_posts_output.txt"
STORAGE_STATE = "facebook_state.json"
INCLUDE_POST_AUTHOR = False
MAX_SCROLLS = 30  # Set MAX_SCROLLS to None for unlimited scrolling.
MAX_STAGNANT_SCROLLS = 10  # Used when MAX_POSTS or MAX_SCROLLS is unlimited.

POST_CARD_SELECTOR = "div[role='feed'] > div"
MESSAGE_SELECTORS = [
    "div[data-ad-preview='message']",
    "div[data-ad-rendering-role='story_message']",
]
QUOTE_SELECTORS = [
    "blockquote.html-blockquote",
    "blockquote",
]
SEE_MORE_LABELS = [
    "See more",
    "Xem thêm",
    "Meer weergeven",
    "Ver más",
    "Mostra altro",
]
SEE_ORIGINAL_LABELS = [
    "See original",
]
TRANSLATION_CONTROL_LABELS = [
    "See original",
    "Hide original",
    "Rate this translation",
    "See translation",
]
UNAVAILABLE_PREVIEW_PHRASES = [
    "This content isn't available right now",
]
SCROLL_STEP_RATIO = 0.85
FACEBOOK_POST_PATTERNS = (
    re.compile(r"^/groups/[^/]+/posts/(\d+)/?$"),
    re.compile(r"^/groups/[^/]+/permalink/(\d+)/?$"),
)
LEADING_DECORATIVE_PREVIEW_SYMBOLS = re.compile(
    r"^(?:[\s\u200b\u200c\u200d\ufe0f]|[\u25a0-\u25ff\U0001F7E5-\U0001F7EB])+\s*"
)
FACEBOOK_GROUP_ROOT_PATTERN = re.compile(r"^/groups/[^/]+/?$")
AUTHOR_TIMESTAMP_PATTERNS = (
    re.compile(r"^(?:just now|now|edited)$", re.IGNORECASE),
    re.compile(r"^\d+\s*(?:s|m|min|h|d|w)$", re.IGNORECASE),
    re.compile(r"^(?:today|yesterday)(?:\s+at\s+.+)?$", re.IGNORECASE),
)
AUTHOR_METADATA_PREFIX = "Author: "
AUTHOR_CANDIDATE_SELECTORS = [
    "[role='heading'] a[href]",
    "h2 a[href]",
    "h3 a[href]",
    "h4 a[href]",
    "strong a[href]",
]
AUTHOR_SKIP_LABELS = {
    *(label.casefold() for label in SEE_MORE_LABELS),
    *(label.casefold() for label in SEE_ORIGINAL_LABELS),
    *(label.casefold() for label in TRANSLATION_CONTROL_LABELS),
    "like",
    "comment",
    "share",
    "follow",
}
AUTHOR_NON_PROFILE_PREFIXES = (
    "/business",
    "/events",
    "/gaming",
    "/hashtag",
    "/help",
    "/marketplace",
    "/photo",
    "/photos",
    "/privacy",
    "/reel",
    "/search",
    "/share",
    "/sharer",
    "/story.php",
    "/watch",
)


def click_all(locator):
    clicked = 0
    for i in range(locator.count()):
        try:
            locator.nth(i).click(timeout=500)
            clicked += 1
        except Exception:
            continue
    return clicked


def expand_visible_posts(page):
    clicked = 0
    for label in SEE_MORE_LABELS:
        clicked += click_all(page.get_by_role("button", name=label, exact=True))
        clicked += click_all(page.locator("div[role='button']", has_text=label))
    return clicked


def expand_post_card(post_card):
    clicked = 0
    for label in SEE_ORIGINAL_LABELS:
        clicked += click_all(post_card.get_by_role("button", name=label, exact=True))
        clicked += click_all(post_card.get_by_role("link", name=label, exact=True))
    return clicked


def clean_message_text(text):
    text = text.strip()
    for label in SEE_MORE_LABELS:
        text = re.sub(rf"\s*…\s*{re.escape(label)}\s*$", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def safe_inner_text(locator, timeout=1000):
    try:
        return locator.inner_text(timeout=timeout)
    except Exception:
        return ""


def safe_get_attribute(locator, name, timeout=1000):
    try:
        return locator.get_attribute(name, timeout=timeout)
    except Exception:
        return None


def extract_accessible_message_text(node):
    tokens = node.evaluate(
        """
        (element) => {
          const out = [];
          const nodes = element.querySelectorAll('img[alt], [role="img"][aria-label]');
          for (const el of nodes) {
            if (el.closest('[hidden], [aria-hidden="true"]')) {
              continue;
            }
            const alt = el.getAttribute('alt');
            const aria = el.getAttribute('aria-label');
            const label = (alt || aria || '').trim();
            if (label) {
              out.push(label);
            }
          }
          return out;
        }
        """
    )
    return clean_message_text(" ".join(tokens))


def clean_quote_text(text):
    if not text:
        return ""

    has_translation_controls = any(label in text for label in TRANSLATION_CONTROL_LABELS)
    if not re.search(r"https?://", text) and not has_translation_controls:
        return ""

    cleaned = text
    for label in TRANSLATION_CONTROL_LABELS:
        cleaned = re.sub(rf"\s*·\s*{re.escape(label)}", "", cleaned)

    # Preview quotes often embed the shared URL inline with the quote text.
    cleaned = re.sub(r"(https?://[^\s\"'”]+)", r"\n\1\n", cleaned)

    groups = []
    current_group = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip(" \t·")
        if not line:
            continue
        if re.fullmatch(r"https?://\S+", line):
            if current_group:
                groups.append(current_group)
                current_group = []
            continue
        if line in TRANSLATION_CONTROL_LABELS:
            continue
        current_group.append(line)

    if current_group:
        groups.append(current_group)

    if not groups:
        return ""

    first_group = groups[0]
    if has_translation_controls and len(first_group) > 1:
        first_group = [first_group[0]]
    elif len(first_group) > 1 and all(
        re.fullmatch(r'["“].*["”]', line) for line in first_group
    ):
        first_group = [first_group[0]]

    return clean_message_text("\n".join(first_group))


def canonicalize_external_url(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)

    for key in list(query):
        if key == "fbclid" or key.startswith("utm_"):
            query.pop(key, None)

    host = parsed.netloc.lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"} and parsed.path == "/watch":
        video_id = query.get("v", [None])[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    if host == "youtu.be":
        video_id = parsed.path.lstrip("/")
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    cleaned_query = urlencode(sorted(query.items()), doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, cleaned_query, ""))


def normalize_outbound_url(url):
    if not url:
        return None

    parsed = urlparse(url)
    if parsed.netloc.lower() in {"l.facebook.com", "lm.facebook.com"}:
        target = parse_qs(parsed.query).get("u", [None])[0]
        if not target:
            return None
        return normalize_outbound_url(unquote(target))

    return canonicalize_external_url(url)


def is_external_url(url):
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return bool(host) and not host.endswith("facebook.com") and not host.endswith("fbcdn.net")


def youtube_url_from_thumbnail(src):
    if not src:
        return None

    if "ytimg.com/vi/" in src:
        video_id = src.split("ytimg.com/vi/", 1)[1].split("/", 1)[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    if "url=" in src and "ytimg.com%2Fvi%2F" in src:
        encoded_url = parse_qs(urlparse(src).query).get("url", [""])[0]
        decoded_url = unquote(encoded_url)
        if "ytimg.com/vi/" in decoded_url:
            video_id = decoded_url.split("ytimg.com/vi/", 1)[1].split("/", 1)[0]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"

    return None


def preview_title_score(title):
    if not title:
        return 0

    title = normalize_inline_whitespace(title)
    if any(phrase.casefold() in title.casefold() for phrase in UNAVAILABLE_PREVIEW_PHRASES):
        return 0

    alnum_chars = "".join(ch for ch in title if ch.isalnum())
    alpha_chars = "".join(ch for ch in title if ch.isalpha())
    if len(alnum_chars) < 3 or len(alpha_chars) < 2:
        return 0

    tokens = [re.sub(r"\W+", "", token) for token in title.split()]
    significant_tokens = [
        token for token in tokens if len(token) >= 3 and any(ch.isalpha() for ch in token)
    ]
    one_char_tokens = [token for token in tokens if len(token) == 1]
    mixed_noise_tokens = [
        token
        for token in tokens
        if len(token) >= 8 and any(ch.isalpha() for ch in token) and any(ch.isdigit() for ch in token)
    ]
    score = len(alnum_chars) + (len(significant_tokens) * 10) - (len(one_char_tokens) * 3)
    score -= len(mixed_noise_tokens) * 25
    if re.search(r"\.com\S", title, re.IGNORECASE):
        score -= 40
    if re.search(r"\d{4}[A-Za-z]", title):
        score -= 20
    return max(score, 0)


def should_replace_preview_title(current_title, candidate_title):
    return preview_title_score(candidate_title) > preview_title_score(current_title)


def add_external_link(entries, url, title=None):
    if not url:
        return

    for entry in entries:
        if entry["url"] == url:
            if title and should_replace_preview_title(entry.get("title"), title):
                entry["title"] = title
            return

    entries.append({"url": url, "title": title})


def canonicalize_facebook_post_url(url):
    if not url:
        return None

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host and not host.endswith("facebook.com"):
        return None

    path = parsed.path.rstrip("/")
    for pattern in FACEBOOK_POST_PATTERNS:
        match = pattern.match(path)
        if match:
            return f"https://www.facebook.com{path}/"

    if parsed.path == "/permalink.php":
        query = parse_qs(parsed.query)
        story_fbid = query.get("story_fbid", [None])[0]
        post_id = query.get("id", [None])[0]
        if story_fbid:
            kept_query = {"story_fbid": story_fbid}
            if post_id:
                kept_query["id"] = post_id
            return urlunparse(
                (
                    "https",
                    "www.facebook.com",
                    parsed.path,
                    "",
                    urlencode(kept_query),
                    "",
                )
            )

    return None


def is_virtualized_placeholder(post_card):
    virtualized = post_card.locator("[data-virtualized]").first
    if virtualized.count() == 0:
        return False
    if safe_get_attribute(virtualized, "data-virtualized") != "true":
        return False
    return not safe_inner_text(post_card) and post_card.locator("a[href]").count() == 0


def extract_post_key(post_card, page_url):
    anchors = post_card.locator("a[href]")
    for i in range(anchors.count()):
        href = safe_get_attribute(anchors.nth(i), "href")
        if not href:
            continue
        # Ignore query-only and fragment-only Facebook control links. On the
        # virtualized feed, Facebook emits many `?__tn__...` and `#?...` hrefs
        # that inherit the current page URL and falsely collapse distinct cards
        # onto the same post key.
        if href.startswith(("?", "#")):
            continue
        canonical_url = canonicalize_facebook_post_url(urljoin(page_url, href))
        if canonical_url:
            return f"url:{canonical_url}"

    positions = post_card.locator("[aria-posinset]")
    for i in range(positions.count()):
        pos = safe_get_attribute(positions.nth(i), "aria-posinset")
        if pos:
            return f"feed-pos:{pos}"

    return None


def has_stable_post_key(post_key):
    return bool(post_key and post_key.startswith("url:"))


def content_dedupe_key(content, prefix="content"):
    if not content:
        return None
    return f"{prefix}:{content}"


def post_is_duplicate(post_key, content, processed_post_keys):
    content_key = content_dedupe_key(content)
    weak_content_key = content_dedupe_key(content, prefix="weak-content")

    if has_stable_post_key(post_key):
        return bool(
            (post_key and post_key in processed_post_keys)
            or (weak_content_key and weak_content_key in processed_post_keys)
        )

    return any(
        key in processed_post_keys
        for key in [post_key, content_key]
        if key
    )


def remember_post_dedupe(post_key, content, processed_post_keys):
    for key in [post_key, content_dedupe_key(content)]:
        if key:
            processed_post_keys.add(key)

    if not has_stable_post_key(post_key):
        weak_content_key = content_dedupe_key(content, prefix="weak-content")
        if weak_content_key:
            processed_post_keys.add(weak_content_key)


def parse_url_only_message_line(line):
    stripped = line.strip()
    if re.fullmatch(r"https?://\S+", stripped):
        return stripped, stripped

    match = re.fullmatch(r"\[(https?://[^\]]+)\]\((https?://[^)]+)\)", stripped)
    if match:
        return match.group(1), match.group(2)

    return None, None


def line_url_matches_external_url(url, external_urls, normalized_external_urls):
    if not url:
        return False

    normalized_url = normalize_outbound_url(url)
    if normalized_url and normalized_url in normalized_external_urls:
        return True

    if url.endswith(("...", "\u2026")):
        prefix = url[:-3] if url.endswith("...") else url[:-1]
        return normalized_url and any(
            external_url.startswith(prefix) for external_url in external_urls
        )

    return False


def dedupe_message_url_lines(message_text, external_urls):
    if not message_text or not external_urls:
        return message_text

    normalized_external_urls = {
        normalized
        for normalized in (normalize_outbound_url(url) for url in external_urls)
        if normalized
    }

    deduped_lines = []
    for line in message_text.splitlines():
        stripped = line.strip()
        if not stripped:
            deduped_lines.append("")
            continue

        display_url, target_url = parse_url_only_message_line(stripped)
        if not target_url:
            deduped_lines.append(line)
            continue

        display_matches = line_url_matches_external_url(
            display_url, external_urls, normalized_external_urls
        )
        target_matches = line_url_matches_external_url(
            target_url, external_urls, normalized_external_urls
        )

        if display_matches and target_matches:
            continue

        normalized_target_url = normalize_outbound_url(target_url)
        if not normalized_target_url or normalized_target_url not in normalized_external_urls:
            normalized_display_url = normalize_outbound_url(display_url)
            if not (
                display_matches
                and target_url.endswith(("...", "\u2026"))
                or target_matches
                and display_url.endswith(("...", "\u2026"))
                or (
                    normalized_display_url
                    and normalized_target_url
                    and normalized_display_url == normalized_target_url
                    and (display_matches or target_matches)
                )
            ):
                deduped_lines.append(line)
            continue

        if display_url.endswith(("...", "\u2026")):
            prefix = display_url[:-3] if display_url.endswith("...") else display_url[:-1]
            if normalized_target_url.startswith(prefix) or any(
                url.startswith(prefix) for url in external_urls
            ):
                continue

        normalized_display_url = normalize_outbound_url(display_url)
        if normalized_display_url and normalized_display_url == normalized_target_url:
            continue

        deduped_lines.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(deduped_lines)).strip()


def normalize_inline_whitespace(text):
    return re.sub(r"\s+", " ", text).strip()


def is_timestamp_like(text):
    return any(pattern.fullmatch(text) for pattern in AUTHOR_TIMESTAMP_PATTERNS)


def clean_author_candidate_text(text):
    if not text:
        return None

    for raw_line in text.splitlines():
        candidate = normalize_inline_whitespace(raw_line).strip("· ")
        if not candidate:
            continue

        parts = [normalize_inline_whitespace(part) for part in re.split(r"\s+·\s+", candidate)]
        if len(parts) > 1 and is_timestamp_like(parts[-1]):
            candidate = " · ".join(part for part in parts[:-1] if part).strip()
        if not candidate:
            continue

        if candidate.casefold() in AUTHOR_SKIP_LABELS:
            continue
        if is_timestamp_like(candidate):
            continue
        if looks_like_url_or_domain(candidate):
            continue
        if len(candidate) > 120 or sum(ch.isalpha() for ch in candidate) < 2:
            continue
        return candidate

    return None


def is_probable_author_facebook_url(url):
    if not url:
        return False

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host and not host.endswith("facebook.com"):
        return False

    if canonicalize_facebook_post_url(url):
        return False

    path = parsed.path.rstrip("/") or "/"
    if path == "/" or FACEBOOK_GROUP_ROOT_PATTERN.fullmatch(path):
        return False

    if path.startswith("/groups/") and "/user/" not in path:
        return False

    return not any(path == prefix or path.startswith(prefix + "/") for prefix in AUTHOR_NON_PROFILE_PREFIXES)


def extract_post_author(post_card, page_url):
    seen_candidates = set()

    def try_candidate(locator):
        href = safe_get_attribute(locator, "href")
        if not href or href.startswith(("?", "#")):
            return None

        absolute_url = urljoin(page_url, href)
        if not is_probable_author_facebook_url(absolute_url):
            return None

        candidate = clean_author_candidate_text(safe_inner_text(locator))
        if not candidate:
            candidate = clean_author_candidate_text(safe_get_attribute(locator, "aria-label") or "")
        if not candidate:
            return None

        key = (candidate.casefold(), absolute_url)
        if key in seen_candidates:
            return None
        seen_candidates.add(key)
        return candidate

    for selector in AUTHOR_CANDIDATE_SELECTORS:
        candidates = post_card.locator(selector)
        for i in range(candidates.count()):
            candidate = try_candidate(candidates.nth(i))
            if candidate:
                return candidate

    fallback_links = post_card.locator("a[href]")
    for i in range(min(fallback_links.count(), 12)):
        candidate = try_candidate(fallback_links.nth(i))
        if candidate:
            return candidate

    return None


def strip_leading_decorative_preview_symbols(text):
    stripped = LEADING_DECORATIVE_PREVIEW_SYMBOLS.sub("", text)
    if stripped and re.match(r"[#A-Za-z0-9]", stripped):
        return stripped
    return text


def looks_like_url_or_domain(text):
    stripped = text.strip().strip("[]()<>.,;:!?")
    if not stripped:
        return False

    if re.fullmatch(r"https?://\S+", stripped):
        return True

    if any(char.isspace() for char in stripped):
        return False

    parsed = urlparse(stripped if "://" in stripped else f"https://{stripped}")
    return bool(parsed.netloc and "." in parsed.netloc)


def clean_preview_title_line(text, candidate_urls):
    title = normalize_inline_whitespace(text)
    if not title:
        return None

    title = strip_leading_decorative_preview_symbols(title)
    title = re.sub(r"^\S+\.com(?=[A-Z])", "", title)
    title = re.sub(r"^([A-Z][a-z]+)([A-Z][a-z]+\b)", r"\1 \2", title)

    for candidate_url in candidate_urls:
        host = urlparse(candidate_url).netloc.lower()
        prefixes = {host}
        if host.startswith("www."):
            prefixes.add(host[4:])
        if host.startswith("m."):
            prefixes.add(host[2:])
        if host.startswith("open."):
            prefixes.add(host[5:])
        for prefix in sorted(prefixes, key=len, reverse=True):
            if prefix and title.casefold().startswith(f"{prefix.casefold()} "):
                title = title[len(prefix) :].strip()
                break

    tokens = [re.sub(r"\W+", "", token) for token in title.split()]
    significant_tokens = [
        token for token in tokens if len(token) >= 3 and any(ch.isalpha() for ch in token)
    ]
    short_tokens = [token for token in tokens if len(token) <= 1]
    if len(tokens) >= 6 and len(significant_tokens) <= 1 and len(short_tokens) >= len(tokens) / 2:
        return None

    parts = [normalize_inline_whitespace(part) for part in re.split(r"\s+·\s+", title)]
    if len(parts) > 1 and looks_like_url_or_domain(parts[-1]):
        title = " · ".join(parts[:-1]).strip()
        if not title:
            return None
    elif len(parts) > 1 and re.match(r"^\d{4}", parts[-1]):
        parts[-1] = re.match(r"^(\d{4})", parts[-1]).group(1)
        title = " · ".join(part for part in parts if part).strip()
        if not title:
            return None

    if title.casefold() in {
        label.casefold()
        for label in SEE_MORE_LABELS + SEE_ORIGINAL_LABELS + TRANSLATION_CONTROL_LABELS
    }:
        return None

    normalized_title_url = normalize_outbound_url(title)
    if normalized_title_url and normalized_title_url in candidate_urls:
        return None

    if looks_like_url_or_domain(title):
        return None

    if preview_title_score(title) == 0:
        return None

    return title


def extract_preview_title(preview_link, candidate_urls):
    seen = set()
    candidate_urls = {url for url in candidate_urls if url}

    for source in [safe_inner_text(preview_link), safe_get_attribute(preview_link, "aria-label") or ""]:
        combined = clean_preview_title_line(source, candidate_urls)
        if combined:
            key = combined.casefold()
            if key not in seen:
                seen.add(key)
                return combined

        for raw_line in source.splitlines():
            cleaned = clean_preview_title_line(raw_line, candidate_urls)
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            return cleaned

    return None


def attach_preview_title(external_links, title, preferred_url=None):
    if not title or preview_title_score(title) == 0:
        return

    normalized_preferred_url = normalize_outbound_url(preferred_url) if preferred_url else None
    if normalized_preferred_url:
        for link in external_links:
            if normalize_outbound_url(link["url"]) == normalized_preferred_url:
                if should_replace_preview_title(link.get("title"), title):
                    link["title"] = title
                return

    untitled_links = [link for link in external_links if not link.get("title")]
    if len(untitled_links) == 1:
        untitled_links[0]["title"] = title
        return

    for link in external_links:
        if should_replace_preview_title(link.get("title"), title):
            link["title"] = title
            return


def get_message_text(post_card):
    parts = []
    for selector in MESSAGE_SELECTORS:
        messages = post_card.locator(selector)
        for i in range(messages.count()):
            node = messages.nth(i)
            text = clean_message_text(safe_inner_text(node))
            if not text:
                text = extract_accessible_message_text(node)
            if text and text not in parts:
                parts.append(text)
    return "\n\n".join(parts).strip()


def get_quote_text(post_card):
    for selector in QUOTE_SELECTORS:
        quotes = post_card.locator(selector)
        for i in range(quotes.count()):
            text = clean_quote_text(safe_inner_text(quotes.nth(i)))
            if text:
                return text
    return ""


def has_url_line(text):
    if not text:
        return False
    return any(re.fullmatch(r"https?://\S+", line.strip()) for line in text.splitlines())


def resolve_preview_url(page, preview_link):
    popup = None
    try:
        preview_link.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass

    try:
        with page.expect_popup(timeout=5000) as popup_info:
            preview_link.click(timeout=3000)
        popup = popup_info.value
        popup.wait_for_load_state("domcontentloaded", timeout=15000)
        popup.wait_for_timeout(1000)
        return normalize_outbound_url(popup.url)
    except Exception:
        return None
    finally:
        if popup:
            try:
                popup.close()
            except Exception:
                pass


def collect_external_links(post_card, page, resolved_preview_urls):
    links = []

    anchors = post_card.locator("a[href]")
    for i in range(anchors.count()):
        href = safe_get_attribute(anchors.nth(i), "href")
        if not href:
            continue
        normalized = normalize_outbound_url(urljoin(page.url, href))
        if is_external_url(normalized):
            add_external_link(links, normalized)

    images = post_card.locator("img[src]")
    for i in range(images.count()):
        derived = youtube_url_from_thumbnail(safe_get_attribute(images.nth(i), "src"))
        if derived:
            add_external_link(links, derived)

    preview_links = post_card.locator("a[target='_blank'][href]")
    for i in range(min(preview_links.count(), 6)):
        preview_link = preview_links.nth(i)
        aria_label = safe_get_attribute(preview_link, "aria-label") or ""
        raw_href = safe_get_attribute(preview_link, "href") or ""
        candidate_urls = [link["url"] for link in links]
        normalized = normalize_outbound_url(urljoin(page.url, raw_href)) if raw_href else None
        if normalized:
            candidate_urls.append(normalized)
        title = extract_preview_title(preview_link, candidate_urls)

        if not raw_href or raw_href.startswith(("?", "#")):
            attach_preview_title(links, title)
            continue
        cache_key = f"{aria_label}|{raw_href}"

        cached_url = resolved_preview_urls.get(cache_key)
        if cached_url:
            add_external_link(links, cached_url, title)
            continue

        if is_external_url(normalized):
            resolved_preview_urls[cache_key] = normalized
            add_external_link(links, normalized, title)
            continue

        resolved_url = resolve_preview_url(page, preview_link)
        resolved_preview_urls[cache_key] = resolved_url
        if is_external_url(resolved_url):
            add_external_link(links, resolved_url, title)

    return links


def format_external_links(external_links):
    separator = "\n\n" if any(link.get("title") for link in external_links) else "\n"
    rendered_links = []
    for link in external_links:
        if link.get("title"):
            rendered_links.append(f"{link['title']}\n{link['url']}")
        else:
            rendered_links.append(link["url"])
    return separator.join(rendered_links)


def extract_post_content(post_card, page, resolved_preview_urls):
    if expand_post_card(post_card):
        page.wait_for_timeout(300)

    post_author = extract_post_author(post_card, page.url) if INCLUDE_POST_AUTHOR else None
    raw_message_text = get_message_text(post_card)
    quote_text = get_quote_text(post_card)
    external_links = collect_external_links(post_card, page, resolved_preview_urls)
    external_urls = [link["url"] for link in external_links]
    message_text = dedupe_message_url_lines(raw_message_text, external_urls)

    if quote_text and quote_text not in (message_text or "") and not has_url_line(raw_message_text):
        message_text = "\n\n".join(part for part in [message_text, quote_text] if part)

    if not message_text and not external_urls:
        return None

    parts = []
    if post_author:
        parts.append(f"{AUTHOR_METADATA_PREFIX}{post_author}")
    if message_text:
        parts.append(message_text)
    if external_links:
        parts.append(format_external_links(external_links))

    return "\n\n".join(parts).strip()


def scroll_feed(page):
    return page.evaluate(
        f"""
        () => {{
            const scrollRoot = document.querySelector('#scrollview');
            const useElementScroll =
                scrollRoot &&
                scrollRoot.scrollHeight > scrollRoot.clientHeight + 20;
            const step = Math.max(400, Math.floor(window.innerHeight * {SCROLL_STEP_RATIO}));
            const before = useElementScroll ? scrollRoot.scrollTop : window.scrollY;
            if (useElementScroll) {{
                scrollRoot.scrollBy(0, step);
            }} else {{
                window.scrollBy(0, step);
            }}
            const after = useElementScroll ? scrollRoot.scrollTop : window.scrollY;
            return {{
                before,
                after,
                moved: after - before,
                step,
                used_element_scroll: Boolean(useElementScroll),
            }};
        }}
        """
    )


def collect_visible_posts(page, posts, processed_post_keys, resolved_preview_urls):
    post_cards = page.locator(POST_CARD_SELECTOR)
    count = post_cards.count()
    print(f"   → {count} feed items found in DOM")

    new_posts = 0
    for i in range(count):
        post_card = post_cards.nth(i)
        if is_virtualized_placeholder(post_card):
            continue
        try:
            content = extract_post_content(post_card, page, resolved_preview_urls)
        except Exception as e:
            print(f"   ⚠️ Error processing feed item {i}: {e}")
            continue
        post_key = extract_post_key(post_card, page.url)
        if content and not post_is_duplicate(post_key, content, processed_post_keys):
            posts.append(content)
            remember_post_dedupe(post_key, content, processed_post_keys)
            new_posts += 1
            print(f"   ✓ Post #{len(posts)} loaded")
            if MAX_POSTS is not None and len(posts) >= MAX_POSTS:
                break

    return new_posts


def run_scraper():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(storage_state=STORAGE_STATE)
        page = ctx.new_page()

        print("🔄 Navigating to group...")
        page.goto(GROUP_URL)
        time.sleep(5)  # wait a bit for feed to load

        posts = []
        scrolls = 0
        stagnant_scrolls = 0
        processed_post_keys = set()
        resolved_preview_urls = {}

        # Collect the initially rendered feed items before scrolling so
        # Facebook's virtualized placeholders do not replace them first.
        while (MAX_POSTS is None or len(posts) < MAX_POSTS) and (
            MAX_SCROLLS is None or scrolls <= MAX_SCROLLS
        ):
            expanded = expand_visible_posts(page)
            if expanded:
                print(f"   ↳ Expanded {expanded} collapsed post sections")
                time.sleep(1)

            new_posts_this_scroll = collect_visible_posts(
                page, posts, processed_post_keys, resolved_preview_urls
            )

            if MAX_POSTS is not None and len(posts) >= MAX_POSTS:
                break

            # When either limit is unlimited, stop after several empty scrolls
            # so the scraper doesn't loop forever once the feed is exhausted.
            if MAX_POSTS is None or MAX_SCROLLS is None:
                if new_posts_this_scroll == 0:
                    stagnant_scrolls += 1
                    print(
                        f"   ⏳ No new posts found on this scroll ({stagnant_scrolls}/{MAX_STAGNANT_SCROLLS})"
                    )
                    if stagnant_scrolls >= MAX_STAGNANT_SCROLLS:
                        print("🛑 Feed appears exhausted. Stopping scraper.")
                        break
                else:
                    stagnant_scrolls = 0

            if MAX_SCROLLS is not None and scrolls >= MAX_SCROLLS:
                break

            if MAX_SCROLLS is None:
                print(f"📜 Scroll {scrolls + 1}…")
            else:
                print(f"📜 Scroll {scrolls + 1}/{MAX_SCROLLS}…")

            scroll_info = scroll_feed(page)
            scrolls += 1
            time.sleep(2)

            if scroll_info["moved"] <= 0 and new_posts_this_scroll == 0:
                stagnant_scrolls += 1
                print(
                    f"   ⏳ Feed did not advance ({stagnant_scrolls}/{MAX_STAGNANT_SCROLLS})"
                )
                if stagnant_scrolls >= MAX_STAGNANT_SCROLLS:
                    print("🛑 Feed appears exhausted. Stopping scraper.")
                    break

        # write results to file
        print(f"✅ Total {len(posts)} posts found. Saving…")
        posts_to_write = posts if MAX_POSTS is None else posts[:MAX_POSTS]
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            for idx, ptext in enumerate(posts_to_write, 1):
                f.write(f"--- POST {idx} ---\n{ptext}\n\n")

        browser.close()
        print(f"📁 Done! Check {OUTPUT_FILE}")


if __name__ == "__main__":
    run_scraper()
