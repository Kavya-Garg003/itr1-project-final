"""
RAG Knowledge Base Scraper — ITR-1 Project
==========================================
Run this locally with:
    pip install playwright beautifulsoup4 markdownify tiktoken lxml requests
    playwright install chromium
    python scraper.py

Output:
    /rag_output/
        raw/        — raw markdown per page
        chunks/     — chunked JSON files ready for embedding
        combined/   — single merged JSONL for ingestion
"""

import json
import os
import re
import time
import hashlib
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

from bs4 import BeautifulSoup
import markdownify
import tiktoken

# ── Output directories ────────────────────────────────────────────────────────
BASE_DIR = Path("rag_output")
RAW_DIR = BASE_DIR / "raw"
CHUNKS_DIR = BASE_DIR / "chunks"
COMBINED_DIR = BASE_DIR / "combined"

for d in [RAW_DIR, CHUNKS_DIR, COMBINED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Tokenizer (cl100k = GPT-4 / text-embedding-3-small compatible) ────────────
enc = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    return len(enc.encode(text))

# ── Chunk config ──────────────────────────────────────────────────────────────
CHUNK_SIZE   = 512   # tokens per chunk
CHUNK_OVERLAP = 64   # token overlap between chunks


# ── Target pages ──────────────────────────────────────────────────────────────
TARGETS = [
    {
        "id":          "itr1_user_manual",
        "url":         "https://www.incometax.gov.in/iec/foportal/help/how-to-file-itr1-form-sahaj",
        "source":      "e-Filing Portal — ITR-1 User Manual",
        "doc_type":    "user_manual",
        "applicable_ay": "AY2024-25",
        "section":     "Filing Procedure",
        # CSS selector for main content on incometax.gov.in pages
        "content_selector": "article.node--type-faq-page, div.node__content, main article, .article-body, .help-content",
        "site_type":   "incometax",
        "wait_for":    "article",  # wait for this element before extracting
    },
    {
        "id":          "itr1_faq",
        "url":         "https://www.incometax.gov.in/iec/foportal/help/e-filing-itr1-form-sahaj-faq",
        "source":      "e-Filing Portal — ITR-1 FAQs",
        "doc_type":    "faq",
        "applicable_ay": "AY2024-25",
        "section":     "FAQs",
        "content_selector": "article.node--type-faq-page, div.node__content, main article, .faq-content",
        "site_type":   "incometax",
        "wait_for":    "article",
    },
    {
        "id":          "salaried_guide",
        "url":         "https://www.incometax.gov.in/iec/foportal/help/individual/return-applicable-1",
        "source":      "e-Filing Portal — Salaried Individuals Guide",
        "doc_type":    "official_guide",
        "applicable_ay": "AY2024-25",
        "section":     "Slab Rates & Eligibility",
        "content_selector": "article.node--type-faq-page, div.node__content, main article, .help-content",
        "site_type":   "incometax",
        "wait_for":    "article",
    },
    {
        "id":          "cleartax_80c",
        "url":         "https://cleartax.in/s/80c-80-deductions",
        "source":      "ClearTax — Section 80C Deductions Guide",
        "doc_type":    "supplementary_guide",
        "applicable_ay": "AY2024-25",
        "section":     "Deductions",
        "content_selector": "article, .article-body, .post-body, [class*='article'], [class*='content-body'], #article-body",
        "site_type":   "cleartax",
        "wait_for":    "article, h1",
    },
    {
        "id":          "cleartax_itr1",
        "url":         "https://cleartax.in/s/itr1",
        "source":      "ClearTax — ITR-1 Form Complete Guide",
        "doc_type":    "supplementary_guide",
        "applicable_ay": "AY2024-25",
        "section":     "ITR-1 Overview",
        "content_selector": "article, .article-body, .post-body, [class*='article'], [class*='content-body'], #article-body",
        "site_type":   "cleartax",
        "wait_for":    "article, h1",
    },
]


# ── Text cleaning ─────────────────────────────────────────────────────────────

BOILERPLATE_PATTERNS = [
    r"skip to (?:main )?content",
    r"call us.*?(?:monday to friday|all days)",
    r"1800\s+\d[\d\s]+",          # helpline numbers
    r"\+91[-\s]\d+",              # phone numbers
    r"(?:08|09)[:\.]\d{2}\s+hrs", # time patterns
    r"login\s*register",
    r"home\s*>\s*",               # breadcrumbs
    r"share this page.*?twitter", # social share blocks
    r"was this (?:page|article) helpful.*?$",
    r"subscribe.*?newsletter",
    r"related articles.*?$",
    r"advertisement",
    r"file now.*?(?:plan|₹)",     # ClearTax CTAs
    r"try cleartax.*?free",
    r"ca-assisted.*?filing",
    r"efile with.*?experts",
]

def clean_text(text: str) -> str:
    """Remove boilerplate, normalize whitespace, fix encoding."""
    # Remove boilerplate
    for pat in BOILERPLATE_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE | re.DOTALL)

    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Collapse excessive spaces
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Strip lines that are just symbols/navigation
    lines = text.split("\n")
    lines = [l.strip() for l in lines if not re.match(r"^[|>\-_=#*\s]{0,5}$", l.strip())]
    text = "\n".join(lines)

    return text.strip()


def html_to_markdown(html: str, base_url: str = "") -> str:
    """Convert HTML to clean markdown, preserving tables and headers."""
    md = markdownify.markdownify(
        html,
        heading_style="ATX",       # ## style headings
        bullets="-",
        strip=["script", "style", "nav", "footer", "header",
               "noscript", "svg", "img", "iframe", "button",
               "form", "aside"],
    )
    return clean_text(md)


# ── Playwright scraping ───────────────────────────────────────────────────────

def scrape_with_playwright(target: dict) -> Optional[str]:
    """
    Use Playwright (headless Chromium) to render the page and extract content.
    Handles both JS-heavy React apps (ClearTax) and Drupal SSR (incometax.gov.in).
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("  ✗ Playwright not installed. Run: pip install playwright && playwright install chromium")
        return None

    print(f"  → Launching browser for: {target['url']}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            extra_http_headers={
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        page = context.new_page()

        # Block images/fonts/media to speed up loading
        page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4,mp3}", lambda r: r.abort())

        try:
            page.goto(target["url"], wait_until="domcontentloaded", timeout=45000)
        except PWTimeout:
            print(f"  ✗ Page load timeout for {target['url']}")
            browser.close()
            return None

        # Wait for content to render
        wait_sel = target.get("wait_for", "body")
        try:
            page.wait_for_selector(wait_sel, timeout=15000)
        except PWTimeout:
            print(f"  ⚠ Wait selector '{wait_sel}' not found — extracting body anyway")

        # Extra wait for JS-heavy sites
        if target["site_type"] == "cleartax":
            time.sleep(3)

        # Try each content selector
        html_content = None
        for selector in target["content_selector"].split(","):
            selector = selector.strip()
            try:
                el = page.query_selector(selector)
                if el:
                    html_content = el.inner_html()
                    print(f"  ✓ Content found via selector: '{selector}'")
                    break
            except Exception:
                continue

        # Fallback: grab the full page body and let BeautifulSoup clean it
        if not html_content:
            print("  ⚠ No selector matched — using full body with aggressive cleaning")
            html_content = page.inner_html("body")

        browser.close()

    return html_content


def extract_content_bs4(html: str, site_type: str) -> str:
    """
    BeautifulSoup post-processing: remove noise, extract clean content.
    Works after Playwright has rendered the JS.
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove all junk elements
    junk_tags = [
        "script", "style", "nav", "footer", "header", "noscript",
        "aside", "form", "figure", "button", "iframe",
    ]
    junk_classes = [
        "breadcrumb", "sidebar", "related", "share", "social",
        "newsletter", "cta", "cookie", "banner", "popup",
        "advertisement", "promo", "sticky", "nav-", "menu",
    ]
    junk_ids = ["sidebar", "footer", "header", "nav", "menu", "cookie"]

    for tag in soup.find_all(junk_tags):
        tag.decompose()

    for el in soup.find_all(True):
        if not hasattr(el, "attrs") or el.attrs is None:
            continue
        cls = el.get("class", [])
        if isinstance(cls, list):
            cls = " ".join(cls)
        elif not isinstance(cls, str):
            cls = str(cls)
        el_id = str(el.get("id", ""))
        if any(j in cls.lower() for j in junk_classes):
            el.decompose()
        elif any(j in el_id.lower() for j in junk_ids):
            el.decompose()

    # Site-specific content extraction
    if site_type == "incometax":
        # Drupal pages — look for node content
        main = (
            soup.find("article")
            or soup.find("div", class_=re.compile(r"node__content|field--body"))
            or soup.find("main")
            or soup
        )
    else:  # cleartax / generic
        main = (
            soup.find("article")
            or soup.find("div", {"id": re.compile(r"article|content|body", re.I)})
            or soup.find("div", class_=re.compile(r"article|content|post", re.I))
            or soup
        )

    return str(main)


# ── Chunking ──────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    chunk_id:       str
    source:         str
    doc_type:       str
    applicable_ay:  str
    section:        str
    url:            str
    text:           str
    token_count:    int
    chunk_index:    int
    total_chunks:   int


def split_into_chunks(text: str, metadata: dict) -> list[Chunk]:
    """
    Semantics-aware chunking:
    1. Split by logical sections (markdown headings / FAQ Q&A pairs)
    2. If a section exceeds CHUNK_SIZE, split further by token count with overlap
    """
    chunks: list[Chunk] = []

    # ── Step 1: Split by logical unit (headings or Q&A) ──────────────────────
    if metadata["doc_type"] == "faq":
        # Split on Q: patterns or ## headings
        logical_blocks = re.split(r"(?=\n#{1,3} |\nQ\d*[:.)]|\nQuestion\s+\d+)", text)
    else:
        # Split on any heading level
        logical_blocks = re.split(r"(?=\n#{1,4} )", text)

    # Remove empty blocks
    logical_blocks = [b.strip() for b in logical_blocks if b.strip()]

    # ── Step 2: Sub-chunk blocks that exceed CHUNK_SIZE ───────────────────────
    raw_chunks: list[str] = []
    for block in logical_blocks:
        tokens = enc.encode(block)
        if len(tokens) <= CHUNK_SIZE:
            raw_chunks.append(block)
        else:
            # Slide a window through the block
            start = 0
            while start < len(tokens):
                end = min(start + CHUNK_SIZE, len(tokens))
                chunk_tokens = tokens[start:end]
                chunk_text = enc.decode(chunk_tokens)
                raw_chunks.append(chunk_text)
                if end == len(tokens):
                    break
                start += CHUNK_SIZE - CHUNK_OVERLAP

    # ── Step 3: Build Chunk objects ───────────────────────────────────────────
    total = len(raw_chunks)
    for i, chunk_text in enumerate(raw_chunks):
        chunk_text = chunk_text.strip()
        if not chunk_text or count_tokens(chunk_text) < 20:
            continue   # skip tiny fragments

        uid = hashlib.md5(f"{metadata['url']}:{i}:{chunk_text[:50]}".encode()).hexdigest()[:12]

        chunks.append(Chunk(
            chunk_id      = f"{metadata['id']}_{i:04d}_{uid}",
            source        = metadata["source"],
            doc_type      = metadata["doc_type"],
            applicable_ay = metadata["applicable_ay"],
            section       = metadata["section"],
            url           = metadata["url"],
            text          = chunk_text,
            token_count   = count_tokens(chunk_text),
            chunk_index   = i,
            total_chunks  = total,
        ))

    return chunks


# ── Main pipeline ─────────────────────────────────────────────────────────────

def process_target(target: dict) -> list[Chunk]:
    print(f"\n{'='*60}")
    print(f"Processing: {target['source']}")
    print(f"URL: {target['url']}")

    # Step 1: Scrape
    html = scrape_with_playwright(target)
    if not html:
        print(f"  ✗ Failed to scrape {target['url']}")
        return []

    # Step 2: BS4 cleaning
    clean_html = extract_content_bs4(html, target["site_type"])

    # Step 3: Convert to markdown
    markdown = html_to_markdown(clean_html, base_url=target["url"])

    if not markdown or len(markdown) < 200:
        print(f"  ✗ Extracted content too short ({len(markdown)} chars) — page may have anti-scraping")
        print("     → Try the manual_fallback.py script for this URL")
        return []

    print(f"  ✓ Extracted {len(markdown):,} characters / ~{count_tokens(markdown):,} tokens")

    # Step 4: Save raw markdown
    raw_path = RAW_DIR / f"{target['id']}.md"
    raw_path.write_text(
        f"# {target['source']}\n\nSource: {target['url']}\nAY: {target['applicable_ay']}\n\n---\n\n{markdown}",
        encoding="utf-8",
    )
    print(f"  ✓ Raw saved → {raw_path}")

    # Step 5: Chunk
    chunks = split_into_chunks(markdown, target)
    print(f"  ✓ {len(chunks)} chunks created")

    # Step 6: Save chunks JSON
    chunks_path = CHUNKS_DIR / f"{target['id']}_chunks.json"
    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in chunks], f, ensure_ascii=False, indent=2)
    print(f"  ✓ Chunks saved → {chunks_path}")

    return chunks


def main():
    print("\n🚀 RAG Knowledge Base Scraper — ITR-1 Project")
    print(f"   Output directory: {BASE_DIR.resolve()}\n")

    all_chunks: list[Chunk] = []

    for target in TARGETS:
        try:
            chunks = process_target(target)
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"  ✗ Error processing {target['id']}: {e}")
            import traceback; traceback.print_exc()

    # Save combined JSONL (one JSON object per line — ideal for batch embedding)
    combined_path = COMBINED_DIR / "all_chunks.jsonl"
    with open(combined_path, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")

    # Summary
    print(f"\n{'='*60}")
    print(f"✅ DONE — {len(all_chunks)} total chunks across {len(TARGETS)} sources")
    print(f"\nOutput files:")
    print(f"  Raw markdown : {RAW_DIR}/")
    print(f"  Chunks JSON  : {CHUNKS_DIR}/")
    print(f"  Combined JSONL: {combined_path}  ← feed this to your embedder")
    print(f"\nChunk breakdown:")

    by_source: dict[str, int] = {}
    for c in all_chunks:
        by_source[c.source] = by_source.get(c.source, 0) + 1
    for src, count in by_source.items():
        print(f"  {count:3d} chunks ← {src}")


if __name__ == "__main__":
    main()
