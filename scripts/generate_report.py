#!/usr/bin/env python3
"""Agrège les rapports JSON Trivy en un rapport global priorisé.

- Lit tous les fichiers *.json présents dans le dossier passé en argument.
- Compte les vulnérabilités CRITICAL et HIGH par image.
- Lit optionnellement images.txt pour récupérer la version cible recommandée
  (syntaxe : "<image> => <image_cible>" — voir images.txt).
- Produit :
    * un rapport Markdown lisible (rapport global + tableau priorisé).
    * un rapport JSON consommable par d'autres outils.

Le script ne fait jamais échouer le pipeline : il termine toujours avec
exit 0 tant que la génération du rapport s'est bien passée.

Usage :
    python3 generate_report.py <reports_dir> <out.md> <out.json>
                              [--images-file <images.txt>]
"""


from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SEVERITIES = ("CRITICAL", "HIGH")
TARGET_UNDEFINED = "à définir"


def load_trivy_report(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Impossible de lire {path}: {exc}", file=sys.stderr)
        return {}


def count_vulns(report: dict[str, Any]) -> dict[str, int]:
    counts = {s: 0 for s in SEVERITIES}
    fixable = {s: 0 for s in SEVERITIES}
    for result in report.get("Results", []) or []:
        for vuln in result.get("Vulnerabilities", []) or []:
            sev = vuln.get("Severity", "").upper()
            if sev in counts:
                counts[sev] += 1
                if vuln.get("FixedVersion"):
                    fixable[sev] += 1
    return {
        "critical": counts["CRITICAL"],
        "high": counts["HIGH"],
        "critical_fixable": fixable["CRITICAL"],
        "high_fixable": fixable["HIGH"],
    }


def image_name(report: dict[str, Any], fallback: str) -> str:
    return (
        report.get("ArtifactName")
        or report.get("Metadata", {}).get("ImageConfig", {}).get("config", {}).get("Image")
        or fallback
    )


def load_targets(images_file: Path | None) -> dict[str, str]:
    """Construit le mapping {image_source: image_cible} depuis images.txt.

    Lignes vides et commentaires ignorés. Lignes sans `=>` n'apparaissent
    pas dans le mapping (la cible sera affichée comme TARGET_UNDEFINED).
    """
    targets: dict[str, str] = {}
    if not images_file or not images_file.is_file():
        return targets
    for raw in images_file.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "=>" not in line:
            continue
        source, target = line.split("=>", 1)
        source = source.strip()
        target = target.strip()
        if source and target:
            targets[source] = target
    return targets


def build_summary(
    reports_dir: Path, targets: dict[str, str]
) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("*.json")):
        report = load_trivy_report(path)
        if not report:
            continue
        counts = count_vulns(report)
        name = image_name(report, path.stem)
        summary.append(
            {
                "image": name,
                "target": targets.get(name, TARGET_UNDEFINED),
                "report_file": path.name,
                **counts,
                "score": counts["critical"] * 10 + counts["high"],
            }
        )
    # Tri prioritaire : CRITICAL desc puis HIGH desc puis nom.
    summary.sort(key=lambda r: (-r["critical"], -r["high"], r["image"]))
    return summary


def render_markdown(summary: list[dict[str, Any]]) -> str:
    total_critical = sum(r["critical"] for r in summary)
    total_high = sum(r["high"] for r in summary)
    total_critical_fix = sum(r["critical_fixable"] for r in summary)
    total_high_fix = sum(r["high_fixable"] for r in summary)

    lines = [
        "# Rapport de vulnérabilités Trivy",
        "",
        f"- Images scannées : **{len(summary)}**",
        f"- Vulnérabilités **CRITICAL** : **{total_critical}** "
        f"(dont **{total_critical_fix}** corrigeables)",
        f"- Vulnérabilités **HIGH** : **{total_high}** "
        f"(dont **{total_high_fix}** corrigeables)",
        "",
        "## Images à mettre à jour par ordre de priorité",
        "",
        "| # | Image | CRITICAL | HIGH | Corrigeables par montée de version (C/H) | Score | Version cible |",
        "|---|-------|----------|------|------------------------------------------|-------|---------------|",
    ]
    for idx, row in enumerate(summary, start=1):
        target_cell = (
            f"`{row['target']}`" if row["target"] != TARGET_UNDEFINED
            else f"_{TARGET_UNDEFINED}_"
        )
        lines.append(
            f"| {idx} | `{row['image']}` | {row['critical']} | {row['high']} "
            f"| {row['critical_fixable']} / {row['high_fixable']} "
            f"| {row['score']} | {target_cell} |"
        )
    if not summary:
        lines.append("| - | _aucun rapport_ | - | - | - | - | - |")

    lines += [
        "",
        "## Méthodologie",
        "",
        "- Le **score** vaut `10 × CRITICAL + HIGH` — il sert uniquement à trier.",
        "- La colonne *Corrigeables par montée de version* indique le nombre de",
        "  vulnérabilités pour lesquelles Trivy connaît une version corrigée —",
        "  ce sont les mises à jour à appliquer en priorité.",
        "- La colonne *Version cible* provient de la syntaxe `image => cible`",
        "  dans `images.txt`. Trivy ne sait pas déduire le tag Docker à viser,",
        "  c'est une décision humaine à reporter dans ce fichier.",
        "- Seules les sévérités `CRITICAL` et `HIGH` sont prises en compte.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports_dir", type=Path)
    parser.add_argument("out_md", type=Path)
    parser.add_argument("out_json", type=Path)
    parser.add_argument(
        "--images-file",
        type=Path,
        default=None,
        help="Fichier listant les images et leurs versions cibles.",
    )
    args = parser.parse_args(argv[1:])

    if not args.reports_dir.is_dir():
        print(f"Dossier introuvable : {args.reports_dir}", file=sys.stderr)
        return 1

    targets = load_targets(args.images_file)
    summary = build_summary(args.reports_dir, targets)
    args.out_md.write_text(render_markdown(summary), encoding="utf-8")

    total_critical = sum(r["critical"] for r in summary)
    total_high = sum(r["high"] for r in summary)
    args.out_json.write_text(
        json.dumps(
            {
                "totals": {"critical": total_critical, "high": total_high},
                "images": summary,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"Rapport généré : {args.out_md} et {args.out_json}")
    print(f"Total CRITICAL : {total_critical} — Total HIGH : {total_high}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
