#!/usr/bin/env python3
"""
Download raw sequencing data referenced in the soil metagenome catalogue.

Automatic sources:
  - INSDC projects/studies/samples/runs through ENA file reports
  - NCBI SRA Toolkit fallback when ENA does not return downloadable FASTQ files
  - MG-RAST public metagenomes and projects
  - Figshare and Zenodo supplementary files
  - accession discovery by scanning downloaded CSV/TSV/TXT/JSON/XML/XLSX supplements

Manual queue:
  - CNCB-NGDC GSA (CRA/PRJCA), NMDC China, CNGBdb, JGI, ggKbase,
    Science Data Bank, PRIDE, and repositories without a stable anonymous file API.

The script intentionally does not discard amplicon, sediment, seawater, suspicious,
or duplicate-looking records unless --metagenomic-only is supplied.
"""

from __future__ import annotations

import argparse
import bz2
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ENA_FILE_REPORT = "https://www.ebi.ac.uk/ena/portal/api/filereport"
MGRAST_API = "https://api.mg-rast.org/1"
FIGSHARE_API = "https://api.figshare.com/v2/articles"
ZENODO_API = "https://zenodo.org/api/records"
USER_AGENT = "soil-metagenome-bulk-downloader/1.0"

INSDC_RE = re.compile(
    r"\b(?:PRJNA|PRJEB|PRJDB|SRP|ERP|DRP|SRA|SRR|ERR|DRR|ERS|SRS|DRS|"
    r"SAMN|SAMEA|SAMD|SRX|ERX|DRX)\d+\b",
    re.I,
)
GSA_RE = re.compile(r"\b(?:CRA|PRJCA)\d+\b", re.I)
NMDC_RE = re.compile(r"\bNMDC\d+\b", re.I)
CNGB_RE = re.compile(r"\bCNP\d+\b", re.I)
PRIDE_RE = re.compile(r"\bPXD\d+\b", re.I)
MG_PROJECT_RE = re.compile(r"\bmgp\d+\b", re.I)
MG_METAGENOME_RE = re.compile(r"\bmgm\d+\.\d+\b", re.I)
MG_NUMERIC_RE = re.compile(r"(?<![\w.])\d{7}\.\d+(?![\w.])")
ZENODO_DOI_RE = re.compile(r"\b10\.5281/zenodo\.(\d+)\b", re.I)
FIGSHARE_DOI_RE = re.compile(r"\b10\.6084/m9\.figshare\.(\d+)\b", re.I)
DRYAD_DOI_RE = re.compile(r"\b10\.5061/dryad\.[A-Za-z0-9.]+\b", re.I)
RANGE_RE = re.compile(
    r"\b(SRR|ERR|DRR|ERS|SRS|DRS|SAMN|SAMEA|SAMD)(\d+)\s*[-–—]\s*"
    r"(?:(SRR|ERR|DRR|ERS|SRS|DRS|SAMN|SAMEA|SAMD))?(\d+)\b",
    re.I,
)


@dataclass
class SourceRecord:
    source_sheet: str
    status: str
    doi: str
    title: str
    database: str
    data_number: str
    description: str

    @property
    def searchable_text(self) -> str:
        return " ; ".join(
            [
                self.database or "",
                self.data_number or "",
                self.description or "",
            ]
        )


@dataclass
class TokenRecord:
    token: str
    kind: str
    papers: set[str] = field(default_factory=set)
    titles: set[str] = field(default_factory=set)
    database_hints: set[str] = field(default_factory=set)
    statuses: set[str] = field(default_factory=set)


@dataclass
class DownloadItem:
    source: str
    accession: str
    run_accession: str
    url: str
    target: Path
    md5: str = ""
    expected_bytes: int = 0
    library_strategy: str = ""
    library_layout: str = ""
    sample_accession: str = ""
    study_accession: str = ""
    experiment_accession: str = ""
    run_alias: str = ""
    experiment_alias: str = ""
    sample_alias: str = ""
    sample_title: str = ""
    instrument_platform: str = ""
    instrument_model: str = ""
    read_count: int = 0
    base_count: int = 0
    papers: set[str] = field(default_factory=set)

    def key(self) -> tuple[str, str]:
        return (self.url, str(self.target))


class DownloadError(RuntimeError):
    pass


def log(message: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def sanitize_name(text: str, default: str = "unknown") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    return cleaned.strip("._") or default


def read_manifest(path: Path) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        required = {
            "source_sheet",
            "status",
            "doi",
            "title",
            "database",
            "data_number",
            "description",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Manifest is missing columns: {sorted(missing)}")
        for row in reader:
            records.append(SourceRecord(**{k: row.get(k, "") for k in required}))
    return records


def read_run_allowlist(path: Path) -> set[str]:
    """Read an explicit INSDC run allowlist from a TSV or one-accession-per-line file."""
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        lines = [line.rstrip("\r\n") for line in fh]

    nonempty = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not nonempty:
        raise ValueError(f"Run allowlist is empty: {path}")

    header = nonempty[0].split("\t")
    normalized = {name.strip().lower(): index for index, name in enumerate(header)}
    run_column = next(
        (normalized[name] for name in ("run_accession", "run", "accession") if name in normalized),
        None,
    )

    values: list[str] = []
    if run_column is None:
        values = [line.split("\t", 1)[0].strip() for line in nonempty]
    else:
        for line in nonempty[1:]:
            columns = line.split("\t")
            if run_column < len(columns):
                values.append(columns[run_column].strip())

    runs = {value.upper() for value in values if value}
    invalid = sorted(run for run in runs if not re.fullmatch(r"(?:SRR|ERR|DRR)\d+", run))
    if invalid:
        raise ValueError(
            "Run allowlist contains non-run or malformed accessions: " + ", ".join(invalid[:20])
        )
    if not runs:
        raise ValueError(f"Run allowlist contains no valid SRR/ERR/DRR accessions: {path}")
    return runs


def expand_ranges(text: str, max_range: int) -> list[str]:
    expanded: list[str] = []
    for match in RANGE_RE.finditer(text.replace("—", "-").replace("–", "-")):
        prefix1, start_text, prefix2, end_text = match.groups()
        prefix1 = prefix1.upper()
        prefix2 = (prefix2 or prefix1).upper()
        if prefix1 != prefix2:
            continue
        start, end = int(start_text), int(end_text)
        if end < start:
            start, end = end, start
        count = end - start + 1
        if count > max_range:
            log(
                f"Range {prefix1}{start_text}-{prefix2}{end_text} has {count} values; "
                f"leaving endpoints only because --max-range={max_range}"
            )
            expanded.extend([f"{prefix1}{start_text}", f"{prefix2}{end_text}"])
            continue
        width = max(len(start_text), len(end_text))
        expanded.extend(f"{prefix1}{number:0{width}d}" for number in range(start, end + 1))
    return expanded


def extract_tokens(record: SourceRecord, max_range: int) -> list[tuple[str, str]]:
    text = record.searchable_text
    tokens: list[tuple[str, str]] = []

    for token in expand_ranges(text, max_range=max_range):
        tokens.append((token.upper(), "insdc"))

    for token in INSDC_RE.findall(text):
        tokens.append((token.upper(), "insdc"))
    for token in GSA_RE.findall(text):
        tokens.append((token.upper(), "gsa"))
    for token in NMDC_RE.findall(text):
        tokens.append((token.upper(), "nmdc"))
    for token in CNGB_RE.findall(text):
        tokens.append((token.upper(), "cngb"))
    for token in PRIDE_RE.findall(text):
        tokens.append((token.upper(), "pride"))
    for token in MG_PROJECT_RE.findall(text):
        tokens.append((token.lower(), "mgrast_project"))
    for token in MG_METAGENOME_RE.findall(text):
        tokens.append((token.lower(), "mgrast_metagenome"))

    if "MG-RAST" in (record.database or "").upper() or "MG-RAST" in text.upper():
        for token in MG_NUMERIC_RE.findall(text):
            tokens.append((f"mgm{token}", "mgrast_metagenome"))

    for match in ZENODO_DOI_RE.finditer(text):
        tokens.append((f"10.5281/zenodo.{match.group(1)}", "zenodo"))
    for match in FIGSHARE_DOI_RE.finditer(text):
        tokens.append((f"10.6084/m9.figshare.{match.group(1)}", "figshare"))
    for token in DRYAD_DOI_RE.findall(text):
        tokens.append((token, "dryad"))

    upper = text.upper()
    if "JGI PROPOSAL" in upper:
        match = re.search(r"JGI\s+proposal\s+(\d+)", text, re.I)
        tokens.append((f"JGI proposal {match.group(1) if match else 'unknown'}", "jgi"))
    if "GGKBASE" in upper:
        match = re.search(r"ggKbase\s+([A-Za-z0-9_.-]+)", text, re.I)
        tokens.append((f"ggKbase {match.group(1) if match else 'record'}", "ggkbase"))
    if "SCIENCE DATA BANK" in upper:
        match = re.search(r"Science Data Bank\s+([A-Za-z0-9_.-]+)", text, re.I)
        tokens.append((f"Science Data Bank {match.group(1) if match else 'record'}", "science_db"))

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in tokens:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def build_token_map(records: list[SourceRecord], max_range: int) -> tuple[dict[str, TokenRecord], list[SourceRecord]]:
    token_map: dict[str, TokenRecord] = {}
    rows_without_tokens: list[SourceRecord] = []
    for record in records:
        extracted = extract_tokens(record, max_range=max_range)
        if not extracted:
            rows_without_tokens.append(record)
            continue
        for token, kind in extracted:
            key = f"{kind}:{token}"
            tr = token_map.setdefault(key, TokenRecord(token=token, kind=kind))
            if record.doi:
                tr.papers.add(record.doi)
            if record.title:
                tr.titles.add(record.title)
            if record.database:
                tr.database_hints.add(record.database)
            if record.status:
                tr.statuses.add(record.status)
    return token_map, rows_without_tokens


def http_request(url: str, *, timeout: int = 30, retries: int = 2, as_json: bool = False) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                if as_json:
                    return json.loads(payload.decode("utf-8"))
                return payload.decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(30, 2 ** attempt))
    raise DownloadError(f"Request failed after {retries} attempts: {url} ({last_error})")


def split_semicolon(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(";") if item.strip()]


def ftp_to_https(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://", "ftp://")):
        if url.startswith("ftp://"):
            return "https://" + url[len("ftp://") :]
        return url
    return "https://" + url


def resolve_ena(
    token: TokenRecord,
    outdir: Path,
    *,
    metagenomic_only: bool,
) -> tuple[list[DownloadItem], str]:
    fields = [
        "run_accession",
        "run_alias",
        "study_accession",
        "sample_accession",
        "sample_alias",
        "sample_title",
        "experiment_accession",
        "experiment_alias",
        "library_strategy",
        "library_layout",
        "instrument_platform",
        "instrument_model",
        "read_count",
        "base_count",
        "fastq_ftp",
        "fastq_md5",
        "fastq_bytes",
        "submitted_ftp",
        "submitted_md5",
        "submitted_bytes",
    ]
    query = urllib.parse.urlencode(
        {
            "accession": token.token,
            "result": "read_run",
            "fields": ",".join(fields),
            "format": "tsv",
            "download": "true",
        }
    )
    url = f"{ENA_FILE_REPORT}?{query}"
    text = http_request(url)
    if not text.strip() or text.lstrip().startswith("<!DOCTYPE"):
        return [], "ENA returned no run report"

    rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
    if not rows:
        return [], "ENA returned zero runs"

    items: list[DownloadItem] = []
    ignored = 0
    for row in rows:
        strategy = (row.get("library_strategy") or "").upper()
        if metagenomic_only and strategy and strategy != "METAGENOMIC":
            ignored += 1
            continue

        run = row.get("run_accession") or token.token
        urls = split_semicolon(row.get("fastq_ftp") or "")
        md5s = split_semicolon(row.get("fastq_md5") or "")
        sizes = split_semicolon(row.get("fastq_bytes") or "")
        source_field = "fastq_ftp"

        if not urls:
            urls = split_semicolon(row.get("submitted_ftp") or "")
            md5s = split_semicolon(row.get("submitted_md5") or "")
            sizes = split_semicolon(row.get("submitted_bytes") or "")
            source_field = "submitted_ftp"

        for index, raw_url in enumerate(urls):
            download_url = ftp_to_https(raw_url)
            filename = Path(urllib.parse.urlparse(download_url).path).name
            if not filename:
                filename = f"{run}_{index + 1}.dat"
            target = outdir / "INSDC" / sanitize_name(run) / filename
            md5 = md5s[index] if index < len(md5s) else ""
            try:
                expected_bytes = int(sizes[index]) if index < len(sizes) and sizes[index] else 0
            except ValueError:
                expected_bytes = 0
            items.append(
                DownloadItem(
                    source=f"ENA:{source_field}",
                    accession=token.token,
                    run_accession=run,
                    url=download_url,
                    target=target,
                    md5=md5,
                    expected_bytes=expected_bytes,
                    library_strategy=row.get("library_strategy") or "",
                    library_layout=row.get("library_layout") or "",
                    sample_accession=row.get("sample_accession") or "",
                    study_accession=row.get("study_accession") or "",
                    experiment_accession=row.get("experiment_accession") or "",
                    run_alias=row.get("run_alias") or "",
                    experiment_alias=row.get("experiment_alias") or "",
                    sample_alias=row.get("sample_alias") or "",
                    sample_title=row.get("sample_title") or "",
                    instrument_platform=row.get("instrument_platform") or "",
                    instrument_model=row.get("instrument_model") or "",
                    read_count=int(row.get("read_count") or 0),
                    base_count=int(row.get("base_count") or 0),
                    papers=set(token.papers),
                )
            )

    note = f"resolved {len(rows)} runs"
    if ignored:
        note += f"; ignored {ignored} non-METAGENOMIC runs"
    if not items and rows:
        note += "; run records contained no FASTQ/submitted file URLs"
    return items, note


def walk_json(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_json(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_json(value)


def find_strings(obj: Any, pattern: re.Pattern[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, str):
        found.update(match.group(0) for match in pattern.finditer(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            found.update(find_strings(value, pattern))
    elif isinstance(obj, list):
        for value in obj:
            found.update(find_strings(value, pattern))
    return found


def resolve_mgrast_project(token: TokenRecord) -> list[str]:
    payload = http_request(f"{MGRAST_API}/project/{token.token}", as_json=True)
    return sorted(value.lower() for value in find_strings(payload, MG_METAGENOME_RE))


def resolve_mgrast_metagenome(token: TokenRecord, outdir: Path) -> tuple[list[DownloadItem], str]:
    mgm = token.token.lower()
    if not mgm.startswith("mgm"):
        mgm = "mgm" + mgm
    payload = http_request(f"{MGRAST_API}/download/{mgm}", as_json=True)

    candidates: list[DownloadItem] = []
    raw_words = ("raw", "upload", "fastq", "fasta", "sequence", "reads")
    reject_words = (
        "protein",
        "sims",
        "annotation",
        "ontology",
        "abundance",
        "taxonomy",
        "functional",
        "cluster",
        "statistics",
    )

    for item in walk_json(payload):
        blob = json.dumps(item, ensure_ascii=False).lower()
        if not any(word in blob for word in raw_words):
            continue
        if any(word in blob for word in reject_words):
            continue

        url = item.get("url") or item.get("download_url") or item.get("link")
        file_id = item.get("file_id") or item.get("file") or item.get("id")
        if not url and file_id:
            url = f"{MGRAST_API}/download/{mgm}?file={urllib.parse.quote(str(file_id))}"
        if not url:
            continue
        url = ftp_to_https(str(url))

        filename = (
            item.get("file_name")
            or item.get("filename")
            or item.get("name")
            or Path(urllib.parse.urlparse(url).path).name
            or f"{mgm}_{file_id or len(candidates) + 1}.dat"
        )
        filename = sanitize_name(str(filename), default=f"{mgm}.dat")
        md5 = str(item.get("md5") or item.get("checksum") or "")
        size_value = item.get("size") or item.get("file_size") or item.get("bytes") or 0
        try:
            expected_bytes = int(size_value)
        except (ValueError, TypeError):
            expected_bytes = 0

        candidates.append(
            DownloadItem(
                source="MG-RAST",
                accession=mgm,
                run_accession=mgm,
                url=url,
                target=outdir / "MGRAST" / mgm / filename,
                md5=md5,
                expected_bytes=expected_bytes,
                papers=set(token.papers),
            )
        )

    unique: dict[tuple[str, str], DownloadItem] = {}
    for item in candidates:
        unique[item.key()] = item
    return list(unique.values()), f"selected {len(unique)} raw-like files from MG-RAST listing"


def resolve_figshare(token: TokenRecord, outdir: Path) -> tuple[list[DownloadItem], str]:
    match = FIGSHARE_DOI_RE.search(token.token)
    if not match:
        return [], "invalid Figshare DOI"
    article_id = match.group(1)
    payload = http_request(f"{FIGSHARE_API}/{article_id}", as_json=True)
    items: list[DownloadItem] = []
    for file_info in payload.get("files", []):
        url = file_info.get("download_url")
        if not url:
            continue
        name = sanitize_name(str(file_info.get("name") or f"figshare_{article_id}_{len(items)+1}"))
        items.append(
            DownloadItem(
                source="Figshare",
                accession=token.token,
                run_accession=f"figshare_{article_id}",
                url=url,
                target=outdir / "secondary" / f"figshare_{article_id}" / name,
                md5=str(file_info.get("supplied_md5") or file_info.get("computed_md5") or ""),
                expected_bytes=int(file_info.get("size") or 0),
                papers=set(token.papers),
            )
        )
    return items, f"resolved {len(items)} Figshare files"


def resolve_zenodo(token: TokenRecord, outdir: Path) -> tuple[list[DownloadItem], str]:
    match = ZENODO_DOI_RE.search(token.token)
    if not match:
        return [], "invalid Zenodo DOI"
    record_id = match.group(1)
    payload = http_request(f"{ZENODO_API}/{record_id}", as_json=True)
    items: list[DownloadItem] = []
    for file_info in payload.get("files", []):
        links = file_info.get("links") or {}
        url = links.get("content") or links.get("self")
        if not url:
            continue
        name = sanitize_name(
            str(file_info.get("key") or file_info.get("filename") or f"zenodo_{record_id}_{len(items)+1}")
        )
        checksum = str(file_info.get("checksum") or "")
        md5 = checksum.split(":", 1)[1] if checksum.lower().startswith("md5:") else ""
        items.append(
            DownloadItem(
                source="Zenodo",
                accession=token.token,
                run_accession=f"zenodo_{record_id}",
                url=url,
                target=outdir / "secondary" / f"zenodo_{record_id}" / name,
                md5=md5,
                expected_bytes=int(file_info.get("size") or 0),
                papers=set(token.papers),
            )
        )
    return items, f"resolved {len(items)} Zenodo files"


def manual_landing_url(kind: str, token: str) -> str:
    if kind == "gsa":
        return f"https://ngdc.cncb.ac.cn/gsa/browse/{urllib.parse.quote(token)}"
    if kind == "nmdc":
        return f"https://nmdc.cn/resource/genomics/project/detail/{urllib.parse.quote(token)}"
    if kind == "cngb":
        return f"https://db.cngb.org/search/project/{urllib.parse.quote(token)}"
    if kind == "pride":
        return f"https://www.ebi.ac.uk/pride/archive/projects/{urllib.parse.quote(token)}"
    if kind == "dryad":
        return f"https://doi.org/{urllib.parse.quote(token, safe='/')}"
    if kind == "jgi":
        return "https://genome.jgi.doe.gov/portal/"
    if kind == "ggkbase":
        return "https://ggkbase.berkeley.edu/"
    if kind == "science_db":
        return "https://www.scidb.cn/"
    return ""


def merge_items(items: Iterable[DownloadItem]) -> list[DownloadItem]:
    merged: dict[tuple[str, str], DownloadItem] = {}
    for item in items:
        key = item.key()
        if key not in merged:
            merged[key] = item
        else:
            merged[key].papers.update(item.papers)
    return sorted(merged.values(), key=lambda item: (item.source, item.run_accession, item.url))


def write_download_manifest(items: list[DownloadItem], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(
            [
                "source",
                "accession",
                "run_accession",
                "library_strategy",
                "library_layout",
                "study_accession",
                "sample_accession",
                "experiment_accession",
                "run_alias",
                "experiment_alias",
                "sample_alias",
                "sample_title",
                "instrument_platform",
                "instrument_model",
                "read_count",
                "base_count",
                "url",
                "target",
                "md5",
                "expected_bytes",
                "papers",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    item.source,
                    item.accession,
                    item.run_accession,
                    item.library_strategy,
                    item.library_layout,
                    item.study_accession,
                    item.sample_accession,
                    item.experiment_accession,
                    item.run_alias,
                    item.experiment_alias,
                    item.sample_alias,
                    item.sample_title,
                    item.instrument_platform,
                    item.instrument_model,
                    item.read_count,
                    item.base_count,
                    item.url,
                    item.target,
                    item.md5,
                    item.expected_bytes,
                    ";".join(sorted(item.papers)),
                ]
            )


def write_rows(path: Path, headers: list[str], rows: Iterable[Iterable[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(headers)
        writer.writerows(rows)


def md5_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_is_valid(item: DownloadItem, verify_md5: bool) -> tuple[bool, str]:
    if not item.target.exists():
        return False, "missing"
    if item.expected_bytes and item.target.stat().st_size != item.expected_bytes:
        return False, f"size mismatch: {item.target.stat().st_size} != {item.expected_bytes}"
    if verify_md5 and item.md5:
        observed = md5_file(item.target)
        if observed.lower() != item.md5.lower():
            return False, f"md5 mismatch: {observed} != {item.md5}"
    return True, "ok"


def make_aria2_input(items: list[DownloadItem], path: Path, verify_md5: bool) -> list[DownloadItem]:
    pending: list[DownloadItem] = []
    with path.open("w", encoding="utf-8") as fh:
        for item in items:
            valid, _ = file_is_valid(item, verify_md5=verify_md5)
            if valid:
                continue
            item.target.parent.mkdir(parents=True, exist_ok=True)
            pending.append(item)
            fh.write(item.url + "\n")
            fh.write(f"  dir={item.target.parent}\n")
            fh.write(f"  out={item.target.name}\n")
            fh.write("  continue=true\n")
            fh.write("  auto-file-renaming=false\n")
            fh.write("  allow-overwrite=true\n")
            if verify_md5 and item.md5:
                fh.write(f"  checksum=md5={item.md5}\n")
    return pending


def run_aria2(items: list[DownloadItem], outdir: Path, jobs: int, connections: int, verify_md5: bool) -> int:
    input_path = outdir / "logs" / "aria2_input.txt"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    pending = make_aria2_input(items, input_path, verify_md5=verify_md5)
    if not pending:
        log("All direct-download files already exist and passed validation.")
        return 0
    cmd = [
        "aria2c",
        f"--input-file={input_path}",
        f"--max-concurrent-downloads={jobs}",
        f"--split={connections}",
        f"--max-connection-per-server={connections}",
        "--min-split-size=64M",
        "--continue=true",
        "--file-allocation=none",
        "--retry-wait=10",
        "--max-tries=0",
        "--timeout=120",
        "--connect-timeout=30",
        "--summary-interval=60",
        "--console-log-level=notice",
    ]
    log(f"Starting aria2c for {len(pending)} files.")
    return subprocess.run(cmd, check=False).returncode


def command_download(item: DownloadItem) -> tuple[DownloadItem, bool, str]:
    item.target.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("curl"):
        cmd = [
            "curl",
            "--fail",
            "--location",
            "--continue-at",
            "-",
            "--retry",
            "8",
            "--retry-all-errors",
            "--connect-timeout",
            "30",
            "--output",
            str(item.target),
            item.url,
        ]
    elif shutil.which("wget"):
        cmd = [
            "wget",
            "--continue",
            "--tries=0",
            "--timeout=120",
            "--output-document",
            str(item.target),
            item.url,
        ]
    else:
        return item, False, "Neither aria2c, curl nor wget is installed"
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        return item, False, result.stderr[-1000:]
    return item, True, "downloaded"


def download_without_aria2(
    items: list[DownloadItem],
    jobs: int,
    verify_md5: bool,
) -> list[tuple[DownloadItem, str]]:
    pending = [item for item in items if not file_is_valid(item, verify_md5=verify_md5)[0]]
    failures: list[tuple[DownloadItem, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as executor:
        futures = {executor.submit(command_download, item): item for item in pending}
        for future in as_completed(futures):
            item, ok, message = future.result()
            if not ok:
                failures.append((item, message))
                log(f"FAILED {item.url}: {message}")
    return failures


def run_sra_fallback(
    accessions: list[TokenRecord],
    outdir: Path,
    threads: int,
) -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    if not (shutil.which("prefetch") and shutil.which("fasterq-dump")):
        return [(item.token, "SRA Toolkit is not installed") for item in accessions]

    cache = outdir / "sra_cache"
    temp = outdir / "tmp"
    cache.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)

    for token in accessions:
        accession = token.token
        fastq_dir = outdir / "INSDC_SRA_fallback" / sanitize_name(accession)
        fastq_dir.mkdir(parents=True, exist_ok=True)
        log(f"SRA fallback: {accession}")
        prefetch_cmd = ["prefetch", accession, "--output-directory", str(cache)]
        result = subprocess.run(prefetch_cmd, text=True, capture_output=True)
        if result.returncode != 0:
            failures.append((accession, "prefetch failed: " + result.stderr[-1000:]))
            continue
        dump_cmd = [
            "fasterq-dump",
            accession,
            "--split-files",
            "--threads",
            str(threads),
            "--temp",
            str(temp),
            "--outdir",
            str(fastq_dir),
        ]
        result = subprocess.run(dump_cmd, text=True, capture_output=True)
        if result.returncode != 0:
            failures.append((accession, "fasterq-dump failed: " + result.stderr[-1000:]))
            continue
        fastqs = list(fastq_dir.glob("*.fastq"))
        if not fastqs:
            failures.append((accession, "fasterq-dump produced no FASTQ files"))
            continue
        if shutil.which("pigz"):
            subprocess.run(["pigz", "-p", str(threads), *map(str, fastqs)], check=False)
        else:
            for fastq in fastqs:
                with fastq.open("rb") as source, gzip.open(str(fastq) + ".gz", "wb", compresslevel=5) as target:
                    shutil.copyfileobj(source, target, length=8 * 1024 * 1024)
                fastq.unlink()
    return failures


def iter_text_from_xlsx(path: Path, max_bytes: int) -> str:
    chunks: list[str] = []
    used = 0
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".xml"):
                continue
            data = archive.read(name)
            used += len(data)
            if max_bytes and used > max_bytes:
                break
            chunks.append(data.decode("utf-8", errors="ignore"))
    return "\n".join(chunks)


def text_from_file(path: Path, max_bytes: int = 300_000_000) -> str:
    suffixes = "".join(path.suffixes).lower()
    if path.suffix.lower() == ".xlsx":
        return iter_text_from_xlsx(path, max_bytes=max_bytes)
    if suffixes.endswith(".gz") and path.stat().st_size <= max_bytes:
        with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as fh:
            return fh.read(max_bytes)
    if suffixes.endswith(".bz2") and path.stat().st_size <= max_bytes:
        with bz2.open(path, "rt", encoding="utf-8", errors="ignore") as fh:
            return fh.read(max_bytes)
    if path.suffix.lower() in {".csv", ".tsv", ".txt", ".json", ".xml", ".md"} and path.stat().st_size <= max_bytes:
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def discover_accessions_in_secondary(items: list[DownloadItem]) -> set[str]:
    accessions: set[str] = set()
    for item in items:
        if item.source not in {"Figshare", "Zenodo"} or not item.target.exists():
            continue
        try:
            text = text_from_file(item.target)
        except Exception as exc:
            log(f"Could not scan {item.target}: {exc}")
            continue
        accessions.update(token.upper() for token in INSDC_RE.findall(text))
        for match in RANGE_RE.finditer(text.replace("—", "-").replace("–", "-")):
            prefix1, start_text, prefix2, end_text = match.groups()
            prefix1 = prefix1.upper()
            prefix2 = (prefix2 or prefix1).upper()
            if prefix1 != prefix2:
                continue
            start, end = int(start_text), int(end_text)
            if end < start:
                start, end = end, start
            if end - start + 1 <= 10000:
                width = max(len(start_text), len(end_text))
                accessions.update(f"{prefix1}{number:0{width}d}" for number in range(start, end + 1))
    return accessions


def total_expected_bytes(items: list[DownloadItem]) -> int:
    return sum(item.expected_bytes for item in items if item.expected_bytes > 0)


def human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if amount < 1024 or unit == "PiB":
            return f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{value} B"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve and download sequencing data referenced by the Excel-derived manifest."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("download_manifest_target.tsv"),
    )
    parser.add_argument("--outdir", type=Path, default=Path("metagenome_downloads"))
    parser.add_argument(
        "--run-allowlist",
        type=Path,
        help=(
            "Hard safety gate: resolve and download only explicit SRR/ERR/DRR runs in this "
            "TSV or one-accession-per-line file. When set, catalogue project accessions are "
            "not expanded and secondary-file discovery is disabled."
        ),
    )
    parser.add_argument("--mode", choices=["resolve", "download", "all"], default="all")
    parser.add_argument("--jobs", type=int, default=4, help="Concurrent file downloads")
    parser.add_argument("--connections", type=int, default=4, help="aria2 connections per file")
    parser.add_argument("--threads", type=int, default=12, help="SRA Toolkit/pigz threads")
    parser.add_argument(
        "--metagenomic-only",
        action="store_true",
        help="Discard non-METAGENOMIC ENA runs. Off by default to preserve problematic data.",
    )
    parser.add_argument(
        "--no-secondary",
        action="store_true",
        help="Do not download Figshare/Zenodo supplementary files.",
    )
    parser.add_argument("--no-md5", action="store_true", help="Skip MD5 validation")
    parser.add_argument("--max-range", type=int, default=10000)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Proceed without an interactive confirmation, even for very large downloads.",
    )
    args = parser.parse_args()

    args.outdir = args.outdir.resolve()
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "logs").mkdir(exist_ok=True)

    records = read_manifest(args.manifest)
    allowed_runs = read_run_allowlist(args.run_allowlist) if args.run_allowlist else None
    if allowed_runs is not None:
        token_map = {
            f"insdc:{run}": TokenRecord(token=run, kind="insdc")
            for run in sorted(allowed_runs)
        }
        rows_without_tokens: list[SourceRecord] = []
        log(
            f"Loaded {len(records)} catalogue rows, but hard-gated resolution to "
            f"{len(allowed_runs)} explicit run accessions from {args.run_allowlist}."
        )
    else:
        token_map, rows_without_tokens = build_token_map(records, max_range=args.max_range)
        log(f"Loaded {len(records)} catalogue rows and extracted {len(token_map)} unique tokens.")

    items: list[DownloadItem] = []
    unresolved: list[tuple[str, str, str, str]] = []
    manual: list[tuple[str, str, str, str, str]] = []
    sra_fallbacks: list[TokenRecord] = []

    mgrast_project_tokens = [token for token in token_map.values() if token.kind == "mgrast_project"]
    for project in mgrast_project_tokens:
        log(f"Resolving MG-RAST project: {project.token}")
        try:
            mgm_ids = resolve_mgrast_project(project)
            if not mgm_ids:
                unresolved.append((project.kind, project.token, "MG-RAST project contained no mgm IDs", ";".join(project.papers)))
                continue
            for mgm in mgm_ids:
                key = f"mgrast_metagenome:{mgm}"
                child = token_map.setdefault(key, TokenRecord(token=mgm, kind="mgrast_metagenome"))
                child.papers.update(project.papers)
                child.titles.update(project.titles)
                child.database_hints.update(project.database_hints)
                child.statuses.update(project.statuses)
        except Exception as exc:
            unresolved.append((project.kind, project.token, str(exc), ";".join(project.papers)))

    token_list = list(token_map.values())
    for index, token in enumerate(token_list, start=1):
        log(f"[{index}/{len(token_list)}] Resolving {token.kind}: {token.token}")
        try:
            if token.kind == "insdc":
                resolved, note = resolve_ena(
                    token,
                    args.outdir,
                    metagenomic_only=args.metagenomic_only,
                )
                if resolved:
                    items.extend(resolved)
                else:
                    sra_fallbacks.append(token)
                    unresolved.append((token.kind, token.token, note + "; queued for SRA Toolkit fallback", ";".join(token.papers)))
            elif token.kind == "mgrast_metagenome":
                resolved, note = resolve_mgrast_metagenome(token, args.outdir)
                if resolved:
                    items.extend(resolved)
                else:
                    unresolved.append((token.kind, token.token, note, ";".join(token.papers)))
            elif token.kind == "figshare" and not args.no_secondary and allowed_runs is None:
                resolved, note = resolve_figshare(token, args.outdir)
                items.extend(resolved)
                if not resolved:
                    unresolved.append((token.kind, token.token, note, ";".join(token.papers)))
            elif token.kind == "zenodo" and not args.no_secondary and allowed_runs is None:
                resolved, note = resolve_zenodo(token, args.outdir)
                items.extend(resolved)
                if not resolved:
                    unresolved.append((token.kind, token.token, note, ";".join(token.papers)))
            elif token.kind in {
                "gsa",
                "nmdc",
                "cngb",
                "pride",
                "dryad",
                "jgi",
                "ggkbase",
                "science_db",
            }:
                manual.append(
                    (
                        token.kind,
                        token.token,
                        manual_landing_url(token.kind, token.token),
                        ";".join(sorted(token.papers)),
                        ";".join(sorted(token.statuses)),
                    )
                )
        except Exception as exc:
            unresolved.append((token.kind, token.token, str(exc), ";".join(token.papers)))

    items = merge_items(items)
    if allowed_runs is not None:
        resolved_runs = {item.run_accession.upper() for item in items if item.run_accession}
        unexpected_runs = sorted(resolved_runs - allowed_runs)
        missing_runs = sorted(allowed_runs - resolved_runs)
        write_rows(
            args.outdir / "logs" / "run_allowlist_audit.tsv",
            ["run_accession", "status"],
            ([run, "resolved"] for run in sorted(resolved_runs & allowed_runs)),
        )
        if unexpected_runs:
            raise DownloadError(
                "Hard allowlist violation; resolver returned unexpected runs: "
                + ", ".join(unexpected_runs[:20])
            )
        if missing_runs:
            write_rows(
                args.outdir / "logs" / "run_allowlist_missing.tsv",
                ["run_accession", "status"],
                ([run, "missing_or_no_direct_file"] for run in missing_runs),
            )
            raise DownloadError(
                "Hard allowlist gate stopped the job because requested runs did not resolve "
                "to direct files: " + ", ".join(missing_runs[:20])
            )
    write_download_manifest(items, args.outdir / "logs" / "resolved_files.tsv")
    write_rows(
        args.outdir / "logs" / "unresolved.tsv",
        ["kind", "token", "reason", "papers"],
        unresolved,
    )
    write_rows(
        args.outdir / "logs" / "manual_download_queue.tsv",
        ["kind", "token", "landing_url", "papers", "catalogue_status"],
        manual,
    )
    write_rows(
        args.outdir / "logs" / "catalogue_rows_without_accessions.tsv",
        ["source_sheet", "status", "doi", "title", "database", "data_number", "description"],
        (
            [
                row.source_sheet,
                row.status,
                row.doi,
                row.title,
                row.database,
                row.data_number,
                row.description,
            ]
            for row in rows_without_tokens
        ),
    )

    known_size = total_expected_bytes(items)
    log(
        f"Resolved {len(items)} direct files. Known total size: {human_bytes(known_size)}. "
        f"Some repositories do not report file sizes, so the real total can be much larger."
    )
    log(f"Manual queue: {len(manual)} tokens; SRA fallback queue: {len(sra_fallbacks)} accessions.")

    if args.mode == "resolve":
        return 0

    if not args.yes and sys.stdin.isatty():
        response = input("Start downloading now? Type YES to continue: ").strip()
        if response != "YES":
            log("Download cancelled after resolution.")
            return 0

    verify_md5 = not args.no_md5
    direct_failures: list[tuple[DownloadItem, str]] = []

    if shutil.which("aria2c"):
        code = run_aria2(
            items,
            outdir=args.outdir,
            jobs=max(1, args.jobs),
            connections=max(1, args.connections),
            verify_md5=verify_md5,
        )
        if code != 0:
            log(f"aria2c returned exit code {code}; validating individual files.")

        # Some confined aria2 installations (notably Snap) can read their own
        # command line but cannot read an input file or write beneath /mnt.  In
        # that case aria2 may return 0 and print "No files to download" even
        # though every requested target is still absent.  Always validate the
        # result and retry only the invalid targets with curl/wget workers.
        post_aria_invalid = [
            item for item in items if not file_is_valid(item, verify_md5=verify_md5)[0]
        ]
        if post_aria_invalid:
            log(
                f"aria2c left {len(post_aria_invalid)} files missing or invalid; "
                "retrying those targets with curl/wget workers."
            )
            direct_failures.extend(
                download_without_aria2(
                    post_aria_invalid,
                    jobs=max(1, args.jobs),
                    verify_md5=verify_md5,
                )
            )
    else:
        log("aria2c is unavailable; using curl/wget workers.")
        direct_failures.extend(
            download_without_aria2(items, jobs=max(1, args.jobs), verify_md5=verify_md5)
        )

    validation_failures: list[tuple[DownloadItem, str]] = []
    for item in items:
        valid, message = file_is_valid(item, verify_md5=verify_md5)
        if not valid:
            validation_failures.append((item, message))

    write_rows(
        args.outdir / "logs" / "failed_direct_downloads.tsv",
        ["source", "accession", "run_accession", "url", "target", "reason", "papers"],
        (
            [
                item.source,
                item.accession,
                item.run_accession,
                item.url,
                item.target,
                reason,
                ";".join(sorted(item.papers)),
            ]
            for item, reason in direct_failures + validation_failures
        ),
    )

    if validation_failures:
        log(
            f"ERROR: {len(validation_failures)} direct-download files are still "
            "missing or invalid after all download engines."
        )
        return 2

    sra_failures = run_sra_fallback(
        sra_fallbacks,
        outdir=args.outdir,
        threads=max(1, args.threads),
    )
    write_rows(
        args.outdir / "logs" / "failed_sra_fallbacks.tsv",
        ["accession", "reason"],
        sra_failures,
    )

    # Scan downloaded Figshare/Zenodo tables for hidden SRA/ENA run lists, then download them.
    if not args.no_secondary and allowed_runs is None:
        discovered = discover_accessions_in_secondary(items)
        existing_insdc = {token.token for token in token_map.values() if token.kind == "insdc"}
        new_accessions = sorted(discovered - existing_insdc)
        log(f"Discovered {len(new_accessions)} new INSDC accessions in downloaded supplements.")
        if new_accessions:
            discovered_items: list[DownloadItem] = []
            discovered_fallbacks: list[TokenRecord] = []
            for accession in new_accessions:
                token = TokenRecord(
                    token=accession,
                    kind="insdc",
                    papers={"discovered_from_supplement"},
                )
                try:
                    resolved, note = resolve_ena(
                        token,
                        args.outdir,
                        metagenomic_only=args.metagenomic_only,
                    )
                    if resolved:
                        discovered_items.extend(resolved)
                    else:
                        discovered_fallbacks.append(token)
                except Exception:
                    discovered_fallbacks.append(token)

            discovered_items = merge_items(discovered_items)
            write_download_manifest(
                discovered_items,
                args.outdir / "logs" / "resolved_from_supplements.tsv",
            )
            if discovered_items:
                if shutil.which("aria2c"):
                    run_aria2(
                        discovered_items,
                        outdir=args.outdir,
                        jobs=max(1, args.jobs),
                        connections=max(1, args.connections),
                        verify_md5=verify_md5,
                    )
                else:
                    download_without_aria2(
                        discovered_items,
                        jobs=max(1, args.jobs),
                        verify_md5=verify_md5,
                    )
            if discovered_fallbacks:
                extra_failures = run_sra_fallback(
                    discovered_fallbacks,
                    outdir=args.outdir,
                    threads=max(1, args.threads),
                )
                write_rows(
                    args.outdir / "logs" / "failed_supplement_sra_fallbacks.tsv",
                    ["accession", "reason"],
                    extra_failures,
                )

    log("Finished. Review logs/manual_download_queue.tsv and all failed_*.tsv files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
