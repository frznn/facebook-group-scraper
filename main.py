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


def add_unique(items, value):
    if value and value not in items:
        items.append(value)


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


def get_message_text(post_card):
    parts = []
    for selector in MESSAGE_SELECTORS:
        messages = post_card.locator(selector)
        for i in range(messages.count()):
            text = clean_message_text(messages.nth(i).inner_text())
            if text and text not in parts:
                parts.append(text)
    return "\n\n".join(parts).strip()


def get_quote_text(post_card):
    for selector in QUOTE_SELECTORS:
        quotes = post_card.locator(selector)
        for i in range(quotes.count()):
            text = clean_quote_text(quotes.nth(i).inner_text())
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


def collect_external_urls(post_card, page, resolved_preview_urls):
    urls = []

    anchors = post_card.locator("a[href]")
    for i in range(anchors.count()):
        href = anchors.nth(i).get_attribute("href")
        if not href:
            continue
        normalized = normalize_outbound_url(urljoin(page.url, href))
        if is_external_url(normalized):
            add_unique(urls, normalized)

    images = post_card.locator("img[src]")
    for i in range(images.count()):
        derived = youtube_url_from_thumbnail(images.nth(i).get_attribute("src"))
        if derived:
            add_unique(urls, derived)

    preview_links = post_card.locator("a[target='_blank'][aria-label]")
    for i in range(min(preview_links.count(), 3)):
        preview_link = preview_links.nth(i)
        aria_label = preview_link.get_attribute("aria-label") or ""
        raw_href = preview_link.get_attribute("href") or ""
        cache_key = f"{aria_label}|{raw_href}"

        cached_url = resolved_preview_urls.get(cache_key)
        if cached_url:
            add_unique(urls, cached_url)
            continue

        normalized = normalize_outbound_url(urljoin(page.url, raw_href)) if raw_href else None
        if is_external_url(normalized):
            resolved_preview_urls[cache_key] = normalized
            add_unique(urls, normalized)
            continue

        resolved_url = resolve_preview_url(page, preview_link)
        resolved_preview_urls[cache_key] = resolved_url
        if is_external_url(resolved_url):
            add_unique(urls, resolved_url)

    return urls


def extract_post_content(post_card, page, resolved_preview_urls):
    if expand_post_card(post_card):
        page.wait_for_timeout(300)

    raw_message_text = get_message_text(post_card)
    quote_text = get_quote_text(post_card)
    external_urls = collect_external_urls(post_card, page, resolved_preview_urls)
    message_text = dedupe_message_url_lines(raw_message_text, external_urls)

    if quote_text and quote_text not in (message_text or "") and not has_url_line(raw_message_text):
        message_text = "\n\n".join(part for part in [message_text, quote_text] if part)

    if not message_text and not external_urls:
        return None

    parts = []
    if message_text:
        parts.append(message_text)
    if external_urls:
        parts.append("\n".join(external_urls))

    return "\n\n".join(parts).strip()


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
        processed_posts = set()  # track processed posts by their content
        resolved_preview_urls = {}

        # keep scrolling until we have MAX_POSTS or reach MAX_SCROLLS
        while (MAX_POSTS is None or len(posts) < MAX_POSTS) and (
            MAX_SCROLLS is None or scrolls < MAX_SCROLLS
        ):
            scrolls += 1
            if MAX_SCROLLS is None:
                print(f"📜 Scroll {scrolls}…")
            else:
                print(f"📜 Scroll {scrolls}/{MAX_SCROLLS}…")

            # scroll the entire page
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)  # wait a bit for new content

            expanded = expand_visible_posts(page)
            if expanded:
                print(f"   ↳ Expanded {expanded} collapsed post sections")
                time.sleep(1)

            post_cards = page.locator(POST_CARD_SELECTOR)
            count = post_cards.count()
            print(f"   → {count} feed items found in DOM")

            new_posts_this_scroll = 0

            # process all feed items and check for new posts
            for i in range(count):
                try:
                    content = extract_post_content(
                        post_cards.nth(i), page, resolved_preview_urls
                    )
                    if content and content not in processed_posts:
                        posts.append(content)
                        processed_posts.add(content)
                        new_posts_this_scroll += 1
                        print(f"   ✓ Post #{len(posts)} loaded")
                        if MAX_POSTS is not None and len(posts) >= MAX_POSTS:
                            break
                except Exception as e:
                    print(f"   ⚠️ Error processing feed item {i}: {e}")
                    continue

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

            # If no new posts found in this scroll, wait a bit more
            if MAX_POSTS is None or len(posts) < MAX_POSTS:
                time.sleep(1)

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
