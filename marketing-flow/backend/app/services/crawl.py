import os, requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote

# ---------- Headers ----------
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36")

DEFAULT_HEADERS = {
    "User-Agent": DESKTOP_UA,
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
}
MOBILE_HEADERS = {**DEFAULT_HEADERS, "User-Agent": MOBILE_UA}

# ---------- Generic fetch & parse ----------
def fetch_html(url: str, timeout: int = 25) -> str:
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.text

def extract_content_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    metas = {}
    for m in soup.find_all("meta"):
        name = (m.get("name") or m.get("property") or m.get("http-equiv") or "").lower()
        content = m.get("content")
        if name and content:
            metas[name] = content
    # basic text
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = " ".join(paragraphs)[:12000]
    # headings (nice for heuristics)
    h1s = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    h2s = [h.get_text(" ", strip=True) for h in soup.find_all("h2")]
    return {"title": title, "metas": metas, "h1": h1s, "h2": h2s, "text": text}

# ---------- Optional headless renderer for JS-heavy pages ----------
try:
    from playwright.sync_api import sync_playwright   # install only if you need render
    HAVE_PLAYWRIGHT = True
except Exception:
    HAVE_PLAYWRIGHT = False

def render_page_fields(url: str, mobile: bool = False) -> dict:
    if not HAVE_PLAYWRIGHT:
        raise RuntimeError("Playwright not installed")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=MOBILE_UA if mobile else DESKTOP_UA,
            locale="vi-VN",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)  # allow JS to paint
        title = page.title() or ""
        html = page.content()
        browser.close()
    fields = extract_content_fields(html)
    if not fields.get("title"):
        fields["title"] = title or "Rendered page"
    fields["metas"] = {**fields.get("metas", {}), "source": "rendered"}
    return fields

# ---------- TikTok helpers ----------
def _is_tiktok(url: str) -> bool:
    return "tiktok.com" in urlparse(url).netloc.lower()

def _is_tiktok_video(url: str) -> bool:
    return _is_tiktok(url) and "/video/" in urlparse(url).path

def _tiktok_oembed_fields(url: str) -> dict:
    api = f"https://www.tiktok.com/oembed?url={quote(url, safe=':/?&=')}"
    r = requests.get(api, headers=DEFAULT_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    caption = data.get("title") or ""
    metas = {
        "author_name": data.get("author_name", ""),
        "author_url": data.get("author_url", ""),
        "thumbnail_url": data.get("thumbnail_url", ""),
        "provider": data.get("provider_name", "TikTok"),
        "note": "TikTok oEmbed (video permalink)"
    }
    return {"title": caption or "TikTok Video", "metas": metas, "h1": [], "h2": [], "text": caption}

# (Optional) TikTok headless if needed (profiles/hashtags)
def tiktok_rendered_fields(url: str) -> dict:
    return render_page_fields(url, mobile=True)

# ---------- Facebook helpers ----------
def _is_facebook(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "facebook.com" in host or "fb.watch" in host

def _fb_mobile_variants(url: str) -> list[str]:
    p = urlparse(url)
    path = p.path + (f"?{p.query}" if p.query else "")
    return [f"https://m.facebook.com{path}", f"https://mbasic.facebook.com{path}"]

def _facebook_extract_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    og_title = soup.find("meta", property="og:title")
    og_desc = soup.find("meta", property="og:description")
    title = (og_title["content"].strip() if og_title and og_title.get("content")
             else (soup.title.get_text(strip=True) if soup.title else "Facebook"))
    desc = og_desc["content"].strip() if og_desc and og_desc.get("content") else ""
    return {"title": title, "metas": {"provider": "Facebook"}, "h1": [], "h2": [], "text": desc}

def facebook_public_fields(url: str) -> dict:
    for candidate in _fb_mobile_variants(url):
        try:
            r = requests.get(candidate, headers=MOBILE_HEADERS, timeout=25, allow_redirects=True)
            if r.status_code == 200:
                f = _facebook_extract_fields(r.text)
                f["metas"]["fetched_url"] = candidate
                if f.get("title") or f.get("text"):
                    return f
        except Exception:
            pass
    try:
        html = fetch_html(url)
        f = extract_content_fields(html)
        f["metas"]["note"] = "Might be a login wall. If empty, the page is not public."
        return f
    except Exception as e:
        return {"title": "Facebook (restricted?)", "metas": {"provider": "Facebook", "error": str(e)}, "h1": [], "h2": [], "text": ""}

# ---------- Smart entry for ALL URLs ----------
def smart_fields(url: str) -> dict:
    """
    - TikTok video → oEmbed (caption)
    - TikTok profile/hashtag → optional render (MFA_TIKTOK_RENDER=1), else guidance
    - Facebook → try mobile/m-basic OG tags
    - Other websites → plain requests; if content looks too thin and MFA_RENDER=1, try headless render
    """
    try:
        # TikTok
        if _is_tiktok(url):
            if _is_tiktok_video(url):
                try:
                    return _tiktok_oembed_fields(url)
                except Exception:
                    if os.getenv("MFA_TIKTOK_RENDER") == "1" and HAVE_PLAYWRIGHT:
                        try:
                            return tiktok_rendered_fields(url)
                        except Exception:
                            pass
                    html = fetch_html(url)
                    return extract_content_fields(html)
            else:
                if os.getenv("MFA_TIKTOK_RENDER") == "1" and HAVE_PLAYWRIGHT:
                    try:
                        return tiktok_rendered_fields(url)
                    except Exception:
                        pass
                return {
                    "title": "TikTok profile/hashtag page",
                    "metas": {"provider": "TikTok",
                             "note": "Use a video permalink (…/video/123…) or enable headless: MFA_TIKTOK_RENDER=1 + Playwright."},
                    "h1": [], "h2": [], "text": ""
                }

        # Facebook
        if _is_facebook(url):
            return facebook_public_fields(url)

        # Generic website
        html = fetch_html(url)
        fields = extract_content_fields(html)

        # If almost no text and rendering is allowed, try headless once
        if os.getenv("MFA_RENDER") == "1" and HAVE_PLAYWRIGHT:
            text_len = len((fields.get("text") or "").strip())
            if text_len < 200:  # threshold: likely JS-only/lazy content
                try:
                    fields = render_page_fields(url, mobile=False)
                except Exception:
                    pass

        return fields

    except Exception as e:
        return {"title": "Fetch error", "metas": {"error": str(e)}, "h1": [], "h2": [], "text": ""}
