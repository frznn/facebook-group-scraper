# Facebook Group Content Scraper

This fork keeps the original Playwright-based Facebook group scraper, but expands it into a more reliable feed scraper for real-world groups with shared links, translated posts, emoji-only posts, and Facebook's virtualized feed rendering.

## Current Features

- Extracts post text from Facebook group feeds using a saved login session
- Expands multiple `See more` labels, including `See more`, `Xem thêm`, `Meer weergeven`, `Ver más`, and `Mostra altro`
- Expands `See original` where Facebook shows translated content
- Can optionally prepend the posting user when Facebook exposes a reliable author link in the feed card
- Extracts outbound links from posts, including resolved preview links, preview titles when Facebook exposes them, and normalized YouTube URLs
- Captures quote text from shared-link previews when the quote contains meaningful text
- Captures emoji-only posts by reading accessible emoji labels from the DOM
- Dedupes duplicate URL lines inside a single post block
- Dedupes feed items by Facebook post identity when possible, instead of collapsing different posts that happen to have the same text
- Scrolls through the feed incrementally so Facebook virtualization is less likely to skip posts
- Supports capped runs or effectively unlimited runs by setting limits to `None`

## Differences From The Original Repo

- The original repo only scraped `div[data-ad-rendering-role='story_message']` text. This fork extracts richer post content, including links, quotes, and emoji-only posts.
- The original repo only clicked the Vietnamese `Xem thêm` button. This fork supports several common `See more` labels and `See original`.
- The original repo deduped posts by text content only. This fork prefers a Facebook post identity key and falls back to content only when necessary.
- The original repo jumped straight to the bottom of the page on each loop. This fork scrolls in smaller steps to reduce skipped posts caused by Facebook feed virtualization.
- The original repo could miss shared-link text, preview links, preview titles, truncated URLs, and markdown-style duplicate link artifacts. This fork handles those cases explicitly.
- The original repo had a single fixed post limit variable. This fork uses `MAX_POSTS`, `MAX_SCROLLS`, and `MAX_STAGNANT_SCROLLS`, and any of the first two can be set to `None`.

## Setup

1. Clone the repo:

```bash
git clone <your-fork-url>
cd facebook-group-scraper
```

2. Create a virtual environment and install Playwright:

```bash
python -m venv .venv
source .venv/bin/activate
pip install playwright
python -m playwright install chromium
```

3. Save a Facebook login session:

```bash
python login_and_save_state.py
```

4. Open `main.py` and set these values:

- `GROUP_URL`: the target Facebook group URL
- `MAX_POSTS`: how many posts to keep, or `None` for no post cap
- `MAX_SCROLLS`: how many scroll steps to allow, or `None` for no scroll cap
- `MAX_STAGNANT_SCROLLS`: how many empty passes to tolerate before stopping an unlimited run
- `OUTPUT_FILE`: where to write the extracted posts
- `INCLUDE_POST_AUTHOR`: whether to prepend `Author: ...` when a post author can be identified

## Usage

Run the login helper once:

```bash
python login_and_save_state.py
```

Then run the scraper:

```bash
python main.py
```

The scraper writes plain-text output in this format:

```text
--- POST 1 ---
[Author: Example User if enabled]

[post text]

[preview title if available]
https://example.com/page

--- POST 2 ---
...
```

When Facebook exposes a shared-preview title, the scraper writes that title on the line above the resolved outbound URL.

## Current Configuration

The current defaults in `main.py` are:

| Variable | Meaning | Default |
| --- | --- | --- |
| `MAX_POSTS` | Maximum posts to save. Set to `None` for no post cap. | `50` |
| `GROUP_URL` | Facebook group URL to scrape. | `YOUR_GROUP_ID_HERE` |
| `OUTPUT_FILE` | Output file path. | `fb_posts_output.txt` |
| `STORAGE_STATE` | Saved Playwright login state. | `facebook_state.json` |
| `INCLUDE_POST_AUTHOR` | Prepend `Author: ...` when a reliable author link is found. | `False` |
| `MAX_SCROLLS` | Maximum incremental scroll passes. Set to `None` for no scroll cap. | `30` |
| `MAX_STAGNANT_SCROLLS` | Stop condition when an unlimited run stops finding new posts. | `10` |

## Notes And Limitations

- The scraper still uses in-file configuration rather than CLI arguments.
- Output is plain text, not JSON or CSV.
- Facebook changes its DOM often, so selectors may need updates over time.
- Some preview links require opening a popup to resolve the final destination, which can slow long runs.
- Post-author extraction is best-effort and only appears when `INCLUDE_POST_AUTHOR` is enabled and Facebook exposes a reliable author link in the feed card.
- Preview titles are best-effort and depend on Facebook exposing readable preview-card text in the feed DOM.
- If Facebook does not expose a stable permalink for a feed item, the scraper falls back to the feed position for deduping within that run.

## Responsible Use

Use this only where you have permission to access the content and where scraping is appropriate. Respect Facebook's terms, privacy expectations, and the group members whose content you are collecting.
