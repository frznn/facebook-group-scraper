from playwright.sync_api import sync_playwright
import time

MAX_POSTS = 50
# Set MAX_POSTS to None to scrape all posts that the feed can still load.
# ⚠️ THAY ĐỔI URL NÀY THÀNH URL NHÓM FACEBOOK CỦA BẠN
GROUP_URL = "https://www.facebook.com/groups/YOUR_GROUP_ID_HERE"
OUTPUT_FILE = "fb_posts_output.txt"
STORAGE_STATE = "facebook_state.json"
MAX_SCROLLS = 30  # Set MAX_SCROLLS to None for unlimited scrolling.
MAX_STAGNANT_SCROLLS = 10  # Used when MAX_POSTS or MAX_SCROLLS is unlimited.


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
        processed_posts = set()  # track processed posts by their text content

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

            # click all "See more" buttons in the feed
            more_buttons = page.locator("text='Xem thêm'")
            for i in range(more_buttons.count()):
                try:
                    more_buttons.nth(i).click(timeout=500)
                except:
                    pass
            time.sleep(1)

            # find all story_message divs
            elems = page.locator("div[data-ad-rendering-role='story_message']")
            count = elems.count()
            print(f"   → {count} elements found in DOM")

            new_posts_this_scroll = 0

            # process all elements and check for new posts
            for i in range(count):
                try:
                    text = elems.nth(i).inner_text().strip()
                    if text and text not in processed_posts:
                        posts.append(text)
                        processed_posts.add(text)
                        new_posts_this_scroll += 1
                        print(f"   ✓ Post #{len(posts)} loaded")
                        if MAX_POSTS is not None and len(posts) >= MAX_POSTS:
                            break
                except Exception as e:
                    print(f"   ⚠️ Error processing element {i}: {e}")
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
