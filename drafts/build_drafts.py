"""Build articles.json (for import_drafts.ps1) and preview/*.html (to read the drafts in a browser)
from articles.py. Run from any folder: py drafts/build_drafts.py"""

import html
import json
import re
from datetime import date
from pathlib import Path

from articles import ARTICLES, IMG

HERE = Path(__file__).resolve().parent
AUTHOR, INITIALS = "RATNESH KUMAR SINGH", "Ratnesh"


def words(text):
    return len(re.sub(r"<[^>]+>", " ", text).split())


def main():
    today = date.today().strftime("%d %b %Y")
    posts = [{
        "title": a["title"],
        "summary": a["summary"],
        "category": a["category"],
        "published_at": today,
        "author": AUTHOR,
        "initials": INITIALS,
        "image_class": "desk",
        "image_url": IMG.format(a["image"]),
        "content": a["content"].strip(),
        "status": "published",
        "active": True,
    } for a in ARTICLES]
    (HERE / "articles.json").write_text(json.dumps(posts, ensure_ascii=False, indent=1), encoding="utf-8")

    preview = HERE / "preview"
    preview.mkdir(exist_ok=True)
    index = []
    for n, post in enumerate(posts, 1):
        name = f"{n:02d}-{re.sub(r'[^a-z0-9]+', '-', post['title'].lower()).strip('-')[:60]}.html"
        # Links in the articles are site-absolute (/mf-sip.html); point them at the live site in the preview.
        body = post["content"].replace('href="/', 'href="https://letmoneyearn.in/')
        (preview / name).write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(post['title'])}</title><style>body{{font:17px/1.7 Georgia,serif;max-width:720px;margin:40px auto;padding:0 20px;color:#17201b}}h1{{line-height:1.15}}img{{width:100%;height:auto}}.meta{{color:#667069;font:13px monospace}}</style></head>
<body><p class="meta"><a href="index.html">All drafts</a> · {post['category']} · {words(post['content'])} words</p><h1>{html.escape(post['title'])}</h1><p><em>{html.escape(post['summary'])}</em></p><img src="{post['image_url']}" alt="">{body}</body></html>""", encoding="utf-8")
        index.append(f'<li><a href="{name}">{html.escape(post["title"])}</a> <small>({post["category"]}, {words(post["content"])} words)</small></li>')
        print(f"{words(post['content']):5d} words  {post['category']:16s} {post['title']}")
    (preview / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Draft articles</title><body style="font:16px/1.6 system-ui;max-width:760px;margin:40px auto;padding:0 20px"><h1>Draft articles</h1><ol>' + "".join(index) + "</ol></body>", encoding="utf-8")
    print(f"{len(posts)} drafts -> {HERE / 'articles.json'} and {preview}")


if __name__ == "__main__":
    main()
