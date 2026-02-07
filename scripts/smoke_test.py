#!/usr/bin/env python3
"""Basic repo smoke tests (no external deps).

What this checks:
- Local asset/link references in HTML exist on disk.
- Duplicate IDs within each HTML file.
- Presence of exactly one <title> and one meta description per page.
- Heuristic: document.getElementById('...') references point to real IDs.
- Inline JS syntax via `node --check` (skips JSON-LD and external scripts).
- sitemap.xml parses as XML.

This is intentionally lightweight so it can run anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class HtmlParseResult:
    ids: set[str]
    duplicate_ids: set[str]
    urls: list[tuple[str, str]]  # (attr, url)
    title_count: int
    meta_desc_count: int


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.duplicate_ids: set[str] = set()
        self.urls: list[tuple[str, str]] = []
        self.title_count = 0
        self.meta_desc_count = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = dict(attrs)

        _id = attrs_dict.get("id")
        if _id:
            if _id in self.ids:
                self.duplicate_ids.add(_id)
            self.ids.add(_id)

        if tag == "title":
            self.title_count += 1

        if tag == "meta" and attrs_dict.get("name") == "description":
            self.meta_desc_count += 1

        for attr in ("href", "src"):
            value = attrs_dict.get(attr)
            if value is not None:
                self.urls.append((attr, value))


URL_IGNORE_PREFIXES = (
    "http://",
    "https://",
    "//",
    "data:",
    "mailto:",
    "tel:",
    "javascript:",
)


def is_local_url(url: str) -> bool:
    url = (url or "").strip()
    if not url:
        return False
    if url.startswith("#"):
        return False
    return not url.startswith(URL_IGNORE_PREFIXES)


SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)


def _script_has_src(attrs: str) -> bool:
    return re.search(r"\bsrc\s*=", attrs, re.IGNORECASE) is not None


def _script_is_jsonld(attrs: str) -> bool:
    return "application/ld+json" in attrs.lower()


def parse_html(html_path: Path) -> tuple[HtmlParseResult, str]:
    content = html_path.read_text(encoding="utf-8")
    parser = LinkParser()
    parser.feed(content)
    return (
        HtmlParseResult(
            ids=parser.ids,
            duplicate_ids=parser.duplicate_ids,
            urls=parser.urls,
            title_count=parser.title_count,
            meta_desc_count=parser.meta_desc_count,
        ),
        content,
    )


def check_html_assets(html_path: Path) -> list[str]:
    result, _content = parse_html(html_path)
    problems: list[str] = []

    if result.duplicate_ids:
        problems.append(f"duplicate ids: {sorted(result.duplicate_ids)}")

    if result.title_count != 1:
        problems.append(f"expected 1 <title>, found {result.title_count}")

    if result.meta_desc_count != 1:
        problems.append(
            f"expected 1 meta description, found {result.meta_desc_count}"
        )

    for attr, url in result.urls:
        if not is_local_url(url):
            continue

        url_no_hash = url.split("#", 1)[0]
        url_no_query = url_no_hash.split("?", 1)[0]
        if not url_no_query:
            continue

        target = (html_path.parent / url_no_query).resolve()

        try:
            target.relative_to(ROOT)
        except ValueError:
            problems.append(f"{attr} points outside repo: {url}")
            continue

        if not target.exists():
            problems.append(f"missing asset referenced via {attr}: {url}")

    return problems


def check_getelementbyid(html_path: Path) -> list[str]:
    result, content = parse_html(html_path)

    id_refs = {
        m.group(1)
        for m in re.finditer(
            r"getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)", content
        )
    }

    missing = sorted([ref for ref in id_refs if ref not in result.ids])
    if missing:
        return [f"JS getElementById references missing ids: {missing}"]
    return []


def check_inline_js_syntax(html_path: Path) -> list[str]:
    problems: list[str] = []
    content = html_path.read_text(encoding="utf-8")

    blocks: list[str] = []
    for attrs, body in SCRIPT_RE.findall(content):
        if _script_has_src(attrs) or _script_is_jsonld(attrs):
            continue
        body = body.strip()
        if not body:
            continue
        blocks.append(body)

    if not blocks:
        return []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for idx, body in enumerate(blocks):
            js_path = tmp_dir / f"{html_path.as_posix().replace('/', '_')}.{idx}.js"
            js_path.write_text(body + "\n", encoding="utf-8")

            try:
                subprocess.run(
                    ["node", "--check", str(js_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError:
                problems.append("node not found; skipped inline JS syntax check")
                return problems
            except subprocess.CalledProcessError as exc:
                problems.append(
                    f"inline JS syntax error (script #{idx}): {(exc.stderr or exc.stdout).strip()}"
                )

    return problems


def check_sitemap() -> list[str]:
    sitemap = ROOT / "sitemap.xml"
    if not sitemap.exists():
        return ["missing sitemap.xml"]

    try:
        ET.parse(sitemap)
    except Exception as exc:  # noqa: BLE001
        return [f"sitemap.xml parse failed: {exc}"]

    return []


def main() -> int:
    html_files = [
        ROOT / "index.html",
        ROOT / "templates" / "circular.html",
        ROOT / "templates" / "morse.html",
        ROOT / "templates" / "barcode.html",
        ROOT / "templates" / "heatmap.html",
        ROOT / "templates" / "constellation.html",
        ROOT / "templates" / "waveform.html",
        ROOT / "templates" / "chord.html",
        ROOT / "templates" / "bubbles.html",
    ]

    failures: dict[Path, list[str]] = {}

    for html in html_files:
        if not html.exists():
            failures[html] = ["missing html file"]
            continue

        problems: list[str] = []
        problems.extend(check_html_assets(html))
        problems.extend(check_getelementbyid(html))
        problems.extend(check_inline_js_syntax(html))

        if problems:
            failures[html] = problems

    sitemap_problems = check_sitemap()
    if sitemap_problems:
        failures[ROOT / "sitemap.xml"] = sitemap_problems

    if failures:
        print("Smoke test failed:\n")
        for path, problems in failures.items():
            rel = path.relative_to(ROOT) if path.is_absolute() else path
            print(f"{rel}:")
            for problem in problems:
                print(f"- {problem}")
            print()
        return 1

    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
