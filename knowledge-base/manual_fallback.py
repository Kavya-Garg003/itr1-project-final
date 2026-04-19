"""
manual_fallback.py — Fallback scraper for anti-bot protected pages
====================================================================
Use this when scraper.py gets blocked (403, empty content, CAPTCHA).

Strategy:
  incometax.gov.in → Uses curl with browser-mimicking headers + cookie jar
  ClearTax         → Uses curl + random delay + referrer spoofing

Run:
    python manual_fallback.py --url "https://cleartax.in/s/itr1" --id cleartax_itr1

Or batch:
    python manual_fallback.py --all

Then re-run the chunker manually:
    python manual_fallback.py --chunk-only
"""

import argparse
import json
import os
import subprocess
import time
import random
import hashlib
from pathlib import Path

from bs4 import BeautifulSoup
import markdownify
import tiktoken

RAW_DIR    = Path("rag_output/raw")
CHUNKS_DIR = Path("rag_output/chunks")
COMBINED   = Path("rag_output/combined/all_chunks.jsonl")
for d in [RAW_DIR, CHUNKS_DIR, COMBINED.parent]:
    d.mkdir(parents=True, exist_ok=True)

enc = tiktoken.get_encoding("cl100k_base")
CHUNK_SIZE    = 512
CHUNK_OVERLAP = 64

FALLBACK_TARGETS = [
    {
        "id":            "itr1_user_manual",
        "url":           "https://www.incometax.gov.in/iec/foportal/help/how-to-file-itr1-form-sahaj",
        "source":        "e-Filing Portal — ITR-1 User Manual",
        "doc_type":      "user_manual",
        "applicable_ay": "AY2024-25",
        "section":       "Filing Procedure",
        "site_type":     "incometax",
    },
    {
        "id":            "itr1_faq",
        "url":           "https://www.incometax.gov.in/iec/foportal/help/e-filing-itr1-form-sahaj-faq",
        "source":        "e-Filing Portal — ITR-1 FAQs",
        "doc_type":      "faq",
        "applicable_ay": "AY2024-25",
        "section":       "FAQs",
        "site_type":     "incometax",
    },
    {
        "id":            "salaried_guide",
        "url":           "https://www.incometax.gov.in/iec/foportal/help/individual/return-applicable-1",
        "source":        "e-Filing Portal — Salaried Individuals Guide",
        "doc_type":      "official_guide",
        "applicable_ay": "AY2024-25",
        "section":       "Slab Rates & Eligibility",
        "site_type":     "incometax",
    },
    {
        "id":            "cleartax_80c",
        "url":           "https://cleartax.in/s/80c-80-deductions",
        "source":        "ClearTax — Section 80C Deductions Guide",
        "doc_type":      "supplementary_guide",
        "applicable_ay": "AY2024-25",
        "section":       "Deductions",
        "site_type":     "cleartax",
    },
    {
        "id":            "cleartax_itr1",
        "url":           "https://cleartax.in/s/itr1",
        "source":        "ClearTax — ITR-1 Form Complete Guide",
        "doc_type":      "supplementary_guide",
        "applicable_ay": "AY2024-25",
        "section":       "ITR-1 Overview",
        "site_type":     "cleartax",
    },
]


# ── curl wrapper ──────────────────────────────────────────────────────────────

CURL_HEADERS_INCOMETAX = [
    "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language: en-IN,en;q=0.9,hi;q=0.7",
    "Accept-Encoding: gzip, deflate, br",
    "Connection: keep-alive",
    "Upgrade-Insecure-Requests: 1",
    "Sec-Fetch-Dest: document",
    "Sec-Fetch-Mode: navigate",
    "Sec-Fetch-Site: none",
    "Cache-Control: max-age=0",
]

CURL_HEADERS_CLEARTAX = [
    "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language: en-IN,en;q=0.9",
    "Referer: https://www.google.com/search?q=itr1+guide+india",
    "Sec-Fetch-Dest: document",
    "Sec-Fetch-Mode: navigate",
    "Sec-Fetch-Site: cross-site",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def curl_fetch(target: dict) -> str | None:
    url = target["url"]
    site_type = target["site_type"]

    ua = random.choice(USER_AGENTS)
    headers = CURL_HEADERS_INCOMETAX if site_type == "incometax" else CURL_HEADERS_CLEARTAX

    # Build curl command
    cmd = ["curl", "-sL", "--compressed", "--max-time", "30",
           "-A", ua, "-c", "/tmp/cookies.txt", "-b", "/tmp/cookies.txt"]
    for h in headers:
        cmd += ["-H", h]
    cmd.append(url)

    print(f"  → curl fetch: {url[:80]}")
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=40)
        html = result.stdout.decode("utf-8", errors="replace")
        if len(html) < 500:
            print(f"  ✗ Got only {len(html)} bytes — likely blocked or CAPTCHA")
            return None
        print(f"  ✓ Got {len(html):,} bytes")
        return html
    except subprocess.TimeoutExpired:
        print("  ✗ curl timed out")
        return None


# ── Content extraction ────────────────────────────────────────────────────────

JUNK_TAGS = ["script", "style", "nav", "footer", "header", "noscript",
             "aside", "form", "button", "iframe", "svg"]
JUNK_CLASSES = ["breadcrumb", "sidebar", "related", "share", "social",
                "newsletter", "cta", "cookie", "banner", "popup",
                "advertisement", "sticky", "nav-"]


def extract_main_content(html: str, site_type: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    # Remove junk
    for tag in soup.find_all(JUNK_TAGS):
        tag.decompose()
    for el in soup.find_all(True):
        cls = " ".join(el.get("class", []))
        if any(j in cls.lower() for j in JUNK_CLASSES):
            el.decompose()

    # Find main content area
    if site_type == "incometax":
        candidates = [
            soup.find("article"),
            soup.find("div", class_=lambda c: c and "node__content" in c),
            soup.find("div", class_=lambda c: c and "field--body" in c),
            soup.find("main"),
        ]
    else:  # cleartax
        candidates = [
            soup.find("article"),
            soup.find("div", {"id": "article-body"}),
            soup.find("div", class_=lambda c: c and any(x in (c or "").lower()
                                                         for x in ["article", "content-body", "post-body"])),
            soup.find("main"),
        ]

    main = next((c for c in candidates if c is not None), soup.body or soup)

    md = markdownify.markdownify(
        str(main),
        heading_style="ATX",
        strip=["script", "style", "nav", "footer", "header", "button", "img"],
    )

    # Clean
    import re
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r"[ \t]{2,}", " ", md)
    return md.strip()


# ── Chunker ───────────────────────────────────────────────────────────────────

def chunk_text(text: str, metadata: dict) -> list[dict]:
    import re
    if metadata["doc_type"] == "faq":
        blocks = re.split(r"(?=\n#{1,3} |\nQ\d*[:.)])", text)
    else:
        blocks = re.split(r"(?=\n#{1,4} )", text)

    blocks = [b.strip() for b in blocks if b.strip()]

    raw_chunks = []
    for block in blocks:
        tokens = enc.encode(block)
        if len(tokens) <= CHUNK_SIZE:
            raw_chunks.append(block)
        else:
            start = 0
            while start < len(tokens):
                end = min(start + CHUNK_SIZE, len(tokens))
                raw_chunks.append(enc.decode(tokens[start:end]))
                if end == len(tokens):
                    break
                start += CHUNK_SIZE - CHUNK_OVERLAP

    chunks = []
    for i, ct in enumerate(raw_chunks):
        ct = ct.strip()
        if len(enc.encode(ct)) < 20:
            continue
        uid = hashlib.md5(f"{metadata['url']}:{i}:{ct[:50]}".encode()).hexdigest()[:12]
        chunks.append({
            "chunk_id":       f"{metadata['id']}_{i:04d}_{uid}",
            "source":         metadata["source"],
            "doc_type":       metadata["doc_type"],
            "applicable_ay":  metadata["applicable_ay"],
            "section":        metadata["section"],
            "url":            metadata["url"],
            "text":           ct,
            "token_count":    len(enc.encode(ct)),
            "chunk_index":    i,
            "total_chunks":   len(raw_chunks),
        })
    return chunks


# ── Main ──────────────────────────────────────────────────────────────────────

def process_one(target: dict):
    print(f"\n{'='*60}")
    print(f"Processing: {target['source']}")

    # Random delay to avoid rate limiting
    delay = random.uniform(2, 5)
    print(f"  Waiting {delay:.1f}s ...")
    time.sleep(delay)

    html = curl_fetch(target)
    if not html:
        print(f"  ✗ Skipped {target['id']}")
        return 0

    md = extract_main_content(html, target["site_type"])
    if len(md) < 200:
        print(f"  ✗ Content too short ({len(md)} chars) — likely blocked")
        print("  → Try: open the page in Chrome, Ctrl+S to save HTML, then run:")
        print(f"         python manual_fallback.py --from-file saved.html --id {target['id']}")
        return 0

    # Save raw
    raw_path = RAW_DIR / f"{target['id']}.md"
    raw_path.write_text(f"# {target['source']}\n\nSource: {target['url']}\n\n---\n\n{md}", encoding="utf-8")
    print(f"  ✓ Raw saved → {raw_path}")

    # Chunk
    chunks = chunk_text(md, target)
    chunk_path = CHUNKS_DIR / f"{target['id']}_chunks.json"
    with open(chunk_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {len(chunks)} chunks → {chunk_path}")
    return len(chunks)


def process_from_file(html_path: str, target_id: str):
    """Process a manually saved HTML file."""
    target = next((t for t in FALLBACK_TARGETS if t["id"] == target_id), None)
    if not target:
        print(f"Unknown target id: {target_id}")
        print(f"Valid ids: {[t['id'] for t in FALLBACK_TARGETS]}")
        return

    html = Path(html_path).read_text(encoding="utf-8", errors="replace")
    md = extract_main_content(html, target["site_type"])
    print(f"Extracted {len(md)} chars")

    raw_path = RAW_DIR / f"{target['id']}.md"
    raw_path.write_text(md, encoding="utf-8")

    chunks = chunk_text(md, target)
    chunk_path = CHUNKS_DIR / f"{target['id']}_chunks.json"
    with open(chunk_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"✓ {len(chunks)} chunks → {chunk_path}")


def rebuild_combined():
    """Merge all chunk files into a single JSONL."""
    all_chunks = []
    for path in sorted(CHUNKS_DIR.glob("*_chunks.json")):
        with open(path, encoding="utf-8") as f:
            all_chunks.extend(json.load(f))
    with open(COMBINED, "w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"✓ Combined JSONL rebuilt → {COMBINED} ({len(all_chunks)} chunks)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Process all fallback targets")
    parser.add_argument("--url", help="Process a specific URL")
    parser.add_argument("--id",  help="Target ID (use with --url or --from-file)")
    parser.add_argument("--from-file", help="Process a manually saved HTML file")
    parser.add_argument("--chunk-only", action="store_true", help="Just rebuild combined JSONL from existing chunks")
    args = parser.parse_args()

    if args.chunk_only:
        rebuild_combined()
    elif args.from_file:
        if not args.id:
            print("--id is required with --from-file")
        else:
            process_from_file(args.from_file, args.id)
            rebuild_combined()
    elif args.all:
        for t in FALLBACK_TARGETS:
            process_one(t)
        rebuild_combined()
    elif args.url and args.id:
        t = next((x for x in FALLBACK_TARGETS if x["id"] == args.id), None)
        if t:
            process_one(t)
            rebuild_combined()
        else:
            print(f"Unknown id: {args.id}")
    else:
        parser.print_help()
