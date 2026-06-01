#!/usr/bin/env python3
"""Convertit le rapport Markdown en HTML auto-contenu (CSS inline).

Le fichier produit est statique et peut être déposé tel quel sur un
Artifactory / serveur web — aucune ressource externe n'est référencée.

Usage : python3 convert_to_html.py <in.md> <out.html> [--title <titre>]
"""

from __future__ import annotations

import argparse
import html
import sys
from datetime import datetime, timezone
from pathlib import Path

import markdown


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --bg: #ffffff;
    --fg: #1f2328;
    --muted: #57606a;
    --border: #d0d7de;
    --row-alt: #f6f8fa;
    --accent: #0969da;
    --critical: #cf222e;
    --high: #bf8700;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    color: var(--fg);
    background: var(--bg);
    max-width: 1100px;
    margin: 2rem auto;
    padding: 0 1.5rem 3rem;
    line-height: 1.55;
  }}
  h1, h2, h3 {{
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.3em;
    margin-top: 1.8em;
  }}
  h1 {{ margin-top: 0; }}
  code {{
    background: var(--row-alt);
    padding: 0.15em 0.35em;
    border-radius: 4px;
    font-size: 0.92em;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 0.94em;
  }}
  th, td {{
    border: 1px solid var(--border);
    padding: 0.55em 0.8em;
    text-align: left;
    vertical-align: top;
  }}
  th {{
    background: var(--row-alt);
    font-weight: 600;
  }}
  tr:nth-child(even) td {{ background: var(--row-alt); }}
  em {{ color: var(--muted); }}
  .meta {{
    color: var(--muted);
    font-size: 0.88em;
    margin-bottom: 1.5em;
  }}
</style>
</head>
<body>
<p class="meta">Généré le {generated_at}</p>
{body}
</body>
</html>
"""


def convert(md_path: Path, html_path: Path, title: str) -> None:
    md_text = md_path.read_text(encoding="utf-8")
    body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html_path.write_text(
        HTML_TEMPLATE.format(
            title=html.escape(title),
            generated_at=html.escape(generated_at),
            body=body,
        ),
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_md", type=Path)
    parser.add_argument("output_html", type=Path)
    parser.add_argument(
        "--title",
        default="Rapport de vulnérabilités Trivy",
        help="Titre HTML de la page.",
    )
    args = parser.parse_args(argv[1:])

    if not args.input_md.is_file():
        print(f"Fichier introuvable : {args.input_md}", file=sys.stderr)
        return 1

    convert(args.input_md, args.output_html, args.title)
    print(f"Rapport HTML généré : {args.output_html}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
