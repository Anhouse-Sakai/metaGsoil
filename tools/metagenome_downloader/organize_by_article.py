#!/usr/bin/env python3
"""
Create one directory per article after the bulk downloader has resolved/downloaded files.

Default behavior uses symbolic links:
  by_article/001_<DOI>__<short_title>/files/...

This keeps the physical files only once in the canonical download directories while
making every article appear to have its own independent file tree.

Modes:
  symlink  - default; no duplicate disk use
  hardlink - no duplicate disk use, same filesystem required
  copy     - physically duplicate files
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Iterable

INSDC_RE = re.compile(
    r"\b(?:PRJNA|PRJEB|PRJDB|SRP|ERP|DRP|SRA|SRR|ERR|DRR|ERS|SRS|DRS|"
    r"SAMN|SAMEA|SAMD|SRX|ERX|DRX)\d+\b",
    re.I,
)
MG_PROJECT_RE = re.compile(r"\bmgp\d+\b", re.I)
MG_METAGENOME_RE = re.compile(r"\bmgm\d+\.\d+\b", re.I)
MG_NUMERIC_RE = re.compile(r"(?<![\w.])\d{7}\.\d+(?![\w.])")
RANGE_RE = re.compile(
    r"\b(SRR|ERR|DRR|ERS|SRS|DRS|SAMN|SAMEA|SAMD)(\d+)\s*[-–—]\s*"
    r"(?:(SRR|ERR|DRR|ERS|SRS|DRS|SAMN|SAMEA|SAMD))?(\d+)\b",
    re.I,
)


def log(message: str) -> None:
    print(f"[organize] {message}", flush=True)


def sanitize(text: str, max_len: int = 100) -> str:
    text = text.strip()
    text = re.sub(r"^https?://doi\.org/", "", text, flags=re.I)
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._-")
    return (text[:max_len].rstrip("._-") or "unknown")


def expand_ranges(text: str, max_range: int = 10000) -> set[str]:
    values: set[str] = set()
    normalized = text.replace("—", "-").replace("–", "-")
    for match in RANGE_RE.finditer(normalized):
        prefix1, start_text, prefix2, end_text = match.groups()
        prefix1 = prefix1.upper()
        prefix2 = (prefix2 or prefix1).upper()
        if prefix1 != prefix2:
            continue
        start, end = int(start_text), int(end_text)
        if end < start:
            start, end = end, start
        if end - start + 1 > max_range:
            values.update({f"{prefix1}{start_text}", f"{prefix2}{end_text}"})
            continue
        width = max(len(start_text), len(end_text))
        values.update(f"{prefix1}{n:0{width}d}" for n in range(start, end + 1))
    return values


def extract_accessions(database: str, data_number: str, description: str) -> set[str]:
    text = " ; ".join([database or "", data_number or "", description or ""])
    values = {token.upper() for token in INSDC_RE.findall(text)}
    values.update(expand_ranges(text))

    for token in MG_PROJECT_RE.findall(text):
        values.add(token.lower())
    for token in MG_METAGENOME_RE.findall(text):
        values.add(token.lower())

    if "MG-RAST" in text.upper():
        for token in MG_NUMERIC_RE.findall(text):
            values.add(f"mgm{token}")

    return values


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def create_article_map(rows: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    articles: dict[str, dict[str, str]] = {}
    accession_to_dois: dict[str, set[str]] = defaultdict(set)

    for index, row in enumerate(rows, start=1):
        doi = (row.get("doi") or "").strip()
        title = (row.get("title") or "").strip()
        if not doi:
            doi = f"NO_DOI_{index:03d}"
        if doi not in articles:
            folder = (
                f"{index:03d}_"
                f"{sanitize(doi, max_len=55)}__"
                f"{sanitize(title, max_len=105)}"
            )
            articles[doi] = {**row, "folder": folder}

        for accession in extract_accessions(
            row.get("database", ""),
            row.get("data_number", ""),
            row.get("description", ""),
        ):
            accession_to_dois[accession].add(doi)

    return articles, accession_to_dois


def ensure_article_info(article_dir: Path, article: dict[str, str]) -> None:
    article_dir.mkdir(parents=True, exist_ok=True)
    info_path = article_dir / "article_info.tsv"
    with info_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(
            [
                "DOI",
                "文章名",
                "状态",
                "数据库",
                "数据号",
                "数据描述",
                "原始工作表",
            ]
        )
        writer.writerow(
            [
                article.get("doi", ""),
                article.get("title", ""),
                article.get("status", ""),
                article.get("database", ""),
                article.get("data_number", ""),
                article.get("description", ""),
                article.get("source_sheet", ""),
            ]
        )


def relative_link_target(source: Path, destination: Path) -> str:
    return os.path.relpath(source, start=destination.parent)


def materialize(source: Path, destination: Path, mode: str) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() or destination.is_symlink():
        try:
            if destination.resolve() == source.resolve():
                return "exists"
        except OSError:
            pass
        destination.unlink()

    if mode == "copy":
        shutil.copy2(source, destination)
        return "copied"

    if mode == "hardlink":
        try:
            os.link(source, destination)
            return "hardlinked"
        except OSError:
            mode = "symlink"

    if mode == "symlink":
        destination.symlink_to(relative_link_target(source, destination))
        return "symlinked"

    raise ValueError(f"Unsupported mode: {mode}")


def read_tsv_if_exists(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def normalize_source(source: str) -> str:
    return sanitize(source.replace(":", "_"), max_len=70)


def create_links_from_resolved(
    outdir: Path,
    article_root: Path,
    articles: dict[str, dict[str, str]],
    mode: str,
) -> tuple[int, list[list[str]]]:
    resolved_path = outdir / "logs" / "resolved_files.tsv"
    rows = read_tsv_if_exists(resolved_path)
    linked = 0
    index_rows: list[list[str]] = []

    for row in rows:
        source_path = Path(row.get("target", ""))
        if not source_path.exists():
            continue

        dois = [value for value in (row.get("papers") or "").split(";") if value]
        for doi in dois:
            article = articles.get(doi)
            if not article:
                continue
            article_dir = article_root / article["folder"]
            target = (
                article_dir
                / "files"
                / normalize_source(row.get("source", "unknown"))
                / sanitize(row.get("run_accession", "") or row.get("accession", "unknown"))
                / source_path.name
            )
            action = materialize(source_path, target, mode)
            linked += action != "exists"
            index_rows.append(
                [
                    doi,
                    article.get("title", ""),
                    row.get("source", ""),
                    row.get("accession", ""),
                    row.get("run_accession", ""),
                    str(source_path),
                    str(target),
                    action,
                ]
            )
    return linked, index_rows


def create_links_from_sra_fallback(
    outdir: Path,
    article_root: Path,
    articles: dict[str, dict[str, str]],
    accession_to_dois: dict[str, set[str]],
    mode: str,
) -> tuple[int, list[list[str]]]:
    root = outdir / "INSDC_SRA_fallback"
    if not root.exists():
        return 0, []

    linked = 0
    index_rows: list[list[str]] = []
    for accession_dir in root.iterdir():
        if not accession_dir.is_dir():
            continue
        accession = accession_dir.name.upper()
        dois = accession_to_dois.get(accession, set())
        if not dois:
            continue
        for source_path in accession_dir.rglob("*"):
            if not source_path.is_file():
                continue
            for doi in dois:
                article = articles.get(doi)
                if not article:
                    continue
                article_dir = article_root / article["folder"]
                target = (
                    article_dir
                    / "files"
                    / "SRA_Toolkit_fallback"
                    / accession_dir.name
                    / source_path.name
                )
                action = materialize(source_path, target, mode)
                linked += action != "exists"
                index_rows.append(
                    [
                        doi,
                        article.get("title", ""),
                        "SRA Toolkit fallback",
                        accession,
                        accession,
                        str(source_path),
                        str(target),
                        action,
                    ]
                )
    return linked, index_rows


def distribute_log_by_papers(
    log_path: Path,
    article_root: Path,
    articles: dict[str, dict[str, str]],
    output_name: str,
) -> int:
    rows = read_tsv_if_exists(log_path)
    if not rows:
        return 0

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        for doi in [value for value in (row.get("papers") or "").split(";") if value]:
            if doi in articles:
                grouped[doi].append(row)

    count = 0
    for doi, article_rows in grouped.items():
        article_dir = article_root / articles[doi]["folder"]
        article_dir.mkdir(parents=True, exist_ok=True)
        output_path = article_dir / output_name
        with output_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=list(article_rows[0].keys()),
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerows(article_rows)
        count += 1
    return count


def write_article_index(article_root: Path, articles: dict[str, dict[str, str]]) -> None:
    path = article_root / "ARTICLE_INDEX.tsv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(
            [
                "序号目录",
                "DOI",
                "文章名",
                "状态",
                "数据库",
                "数据号",
                "原始工作表",
            ]
        )
        for doi, article in articles.items():
            writer.writerow(
                [
                    article["folder"],
                    doi,
                    article.get("title", ""),
                    article.get("status", ""),
                    article.get("database", ""),
                    article.get("data_number", ""),
                    article.get("source_sheet", ""),
                ]
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Organize downloaded data into one directory per article.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("download_manifest_target.tsv"),
    )
    parser.add_argument("--outdir", type=Path, default=Path("metagenome_downloads"))
    parser.add_argument(
        "--mode",
        choices=["symlink", "hardlink", "copy"],
        default="symlink",
        help="How article folders should reference canonical files.",
    )
    args = parser.parse_args()

    outdir = args.outdir.resolve()
    article_root = outdir / "by_article"
    article_root.mkdir(parents=True, exist_ok=True)

    rows = read_manifest(args.manifest)
    articles, accession_to_dois = create_article_map(rows)

    for article in articles.values():
        ensure_article_info(article_root / article["folder"], article)
    write_article_index(article_root, articles)

    direct_count, direct_index = create_links_from_resolved(
        outdir,
        article_root,
        articles,
        args.mode,
    )
    fallback_count, fallback_index = create_links_from_sra_fallback(
        outdir,
        article_root,
        articles,
        accession_to_dois,
        args.mode,
    )

    all_index = direct_index + fallback_index
    index_path = article_root / "FILE_INDEX.tsv"
    with index_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(
            [
                "DOI",
                "文章名",
                "来源",
                "accession",
                "run_accession",
                "实际文件",
                "文章目录文件",
                "操作",
            ]
        )
        writer.writerows(all_index)

    distributed = 0
    distributed += distribute_log_by_papers(
        outdir / "logs" / "manual_download_queue.tsv",
        article_root,
        articles,
        "manual_download_queue.tsv",
    )
    distributed += distribute_log_by_papers(
        outdir / "logs" / "unresolved.tsv",
        article_root,
        articles,
        "unresolved.tsv",
    )
    distributed += distribute_log_by_papers(
        outdir / "logs" / "failed_direct_downloads.tsv",
        article_root,
        articles,
        "failed_direct_downloads.tsv",
    )

    log(f"Created {len(articles)} article directories.")
    log(f"Added {direct_count + fallback_count} file references using mode={args.mode}.")
    log(f"Distributed {distributed} article-specific log files.")
    log(f"Article root: {article_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
