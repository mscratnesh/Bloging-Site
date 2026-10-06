"""SEO checks for every public page (the rules in README.md, "SEO checklist for public pages").
No network. Run from the repo root with:  py -m unittest tests.test_seo
Run it after adding, renaming or changing any page; it must pass before a deploy."""

import html
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import app  # noqa: E402

SITE = "https://letmoneyearn.in/"
NOT_PUBLIC = {"post.html", "googlee92790d0c8d2eb4b.html"}   # post.html is filled per article by the server
TITLE_MAX, DESC_MIN, DESC_MAX = 65, 70, 160


def pages():
    for path in sorted(ROOT.glob("*.html")):
        if path.name.startswith("admin") or path.name in NOT_PUBLIC:
            continue
        yield path.name, path.read_text(encoding="utf-8")


def meta(text, attr, name):
    m = re.search(rf'<meta {attr}="{re.escape(name)}" content="([^"]*)"', text)
    return html.unescape(m.group(1)) if m else None


class Seo(unittest.TestCase):
    def test_every_public_page(self):
        sitemap = set(app.SITEMAP_STATIC_PAGES)
        problems = []
        for name, text in pages():
            bad = lambda msg: problems.append(f"{name}: {msg}")
            robots = meta(text, "name", "robots") or ""
            indexed = "noindex" not in robots
            title = re.search(r"<title>(.*?)</title>", text, re.S)
            title = html.unescape(title.group(1).strip()) if title else ""
            desc = meta(text, "name", "description") or ""
            if not title:
                bad("no <title>")
            elif indexed and len(title) > TITLE_MAX:
                bad(f"title is {len(title)} chars (max {TITLE_MAX}): {title}")
            if indexed and name != "index.html" and not title.endswith("| Let Money Earn"):
                bad("title should end with '| Let Money Earn'")       # the home page leads with the brand instead
            if not desc:
                bad("no meta description")
            elif indexed and not DESC_MIN <= len(desc) <= DESC_MAX:
                bad(f"description is {len(desc)} chars (want {DESC_MIN}-{DESC_MAX})")
            if 'name="viewport"' not in text:
                bad("no viewport meta")
            if not indexed:
                if name in sitemap:
                    bad("noindex page is in SITEMAP_STATIC_PAGES")
                continue
            canonical = SITE + ("" if name == "index.html" else name)
            if f'<link rel="canonical" href="{canonical}">' not in text:
                bad(f"canonical should be {canonical}")
            if not robots.startswith("index, follow"):
                bad("robots meta should be 'index, follow, max-image-preview:large'")
            for attr, key in (("property", "og:title"), ("property", "og:description"), ("property", "og:url"),
                              ("property", "og:image"), ("property", "og:type"), ("name", "twitter:card")):
                if not meta(text, attr, key):
                    bad(f"missing {key}")
            if meta(text, "property", "og:url") not in (None, canonical):
                bad("og:url doesn't match the canonical")
            if len(re.findall(r"<h1[\s>]", text)) != 1:
                bad("should have exactly one <h1>")
            if (name != "index.html" and name not in sitemap):
                bad("indexable page missing from SITEMAP_STATIC_PAGES in app.py")
        for page in sitemap:
            if page and not (ROOT / page).is_file():
                problems.append(f"SITEMAP_STATIC_PAGES lists {page}, which doesn't exist")
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_every_page_has_the_same_menu(self):
        menus = {}
        for name, text in pages():
            m = re.search(r'<header class="site-header">.*?</header>', text, re.S)
            if m:
                menu = re.sub(r"\s+", " ", m.group(0)).replace('href="#top"', 'href="index.html"')
                menus.setdefault(menu.replace('href="#', 'href="index.html#'), []).append(name)   # home links in-page
        self.assertEqual(len(menus), 1, "pages with a different menu: " + "; ".join(
            ", ".join(v) for v in sorted(menus.values(), key=len)[:-1]))


if __name__ == "__main__":
    unittest.main()
