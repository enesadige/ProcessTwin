import re
from dataclasses import dataclass

from apps.rag.corpus_utils import content_hash

MAX_CHARS = 1800
OVERLAP_CHARS = 200
CHUNKING_VERSION = "heading-char-v1"
HEADING_RE = re.compile(r"^(#{1,3})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
CODE_RE = re.compile(
    r"(?<![A-Za-z0-9_-])([A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+)(?![A-Za-z0-9_-])"
)


@dataclass(frozen=True)
class ChunkSpec:
    sequence: int
    heading: str
    section_path: list[str]
    text: str
    char_start: int
    char_end: int
    content_hash: str
    rule_code: str | None
    rule_version: int | None
    metadata: dict


def build_chunk_specs(source_document, *, max_chars=MAX_CHARS, overlap_chars=OVERLAP_CHARS):
    content = source_document.content
    sections = parse_sections(content)
    source_metadata = source_document.metadata or {}
    allowed_rules = set(source_metadata.get("rule_refs", []))
    allowed_alarms = set(source_metadata.get("alarm_refs", []))
    allowed_cases = set(source_metadata.get("ground_truth_refs", []))
    specs = []
    for section in sections:
        for piece in split_section(
            content,
            section,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        ):
            text = content[piece["char_start"] : piece["char_end"]]
            if not text.strip():
                continue
            codes = set(CODE_RE.findall(text))
            rule_refs = sorted(codes & allowed_rules)
            alarm_refs = sorted(codes & allowed_alarms)
            ground_truth_refs = sorted(codes & allowed_cases)
            rule_code = rule_refs[0] if len(rule_refs) == 1 else None
            rule_version = refund_rule_version(source_document, rule_refs)
            metadata = {
                "chunking_version": CHUNKING_VERSION,
                "max_chars": max_chars,
                "overlap_chars": overlap_chars,
                "source_content_hash": source_document.content_hash,
                "source_document_code": source_document.document_code,
                "source_document_version": source_document.version,
                "source_snapshot_key": (
                    source_document.data_snapshot.snapshot_key
                    if source_document.data_snapshot_id
                    else None
                ),
                "normalization_version": "lf-nfc-trim-final-newline-v1",
                "rule_refs": rule_refs,
                "alarm_refs": alarm_refs,
                "ground_truth_refs": ground_truth_refs,
                "overlap_applied": piece["overlap_applied"],
                "split_reason": piece["split_reason"],
            }
            specs.append(
                ChunkSpec(
                    sequence=len(specs),
                    heading=section["heading"],
                    section_path=section["section_path"],
                    text=text,
                    char_start=piece["char_start"],
                    char_end=piece["char_end"],
                    content_hash=content_hash(text),
                    rule_code=rule_code,
                    rule_version=rule_version,
                    metadata=metadata,
                )
            )
    return specs


def parse_sections(content):
    matches = list(HEADING_RE.finditer(content))
    sections = []
    stack = []
    if matches and matches[0].start() > 0:
        sections.append({"heading": "", "section_path": [], "start": 0, "end": matches[0].start()})
    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        stack = stack[: level - 1]
        stack.append(title)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        sections.append(
            {
                "heading": title,
                "section_path": list(stack),
                "start": match.start(),
                "end": end,
                "heading_end": match.end(),
            }
        )
    if not sections and content.strip():
        sections.append({"heading": "", "section_path": [], "start": 0, "end": len(content)})
    return sections


def split_section(content, section, *, max_chars, overlap_chars):
    start = section["start"]
    end = section["end"]
    if end - start <= max_chars:
        return [
            {
                "char_start": start,
                "char_end": end,
                "overlap_applied": False,
                "split_reason": "section",
            }
        ]

    units = natural_units(content, section)
    pieces = []
    current_start = None
    current_end = None
    for unit_start, unit_end in units:
        if unit_end <= unit_start or not content[unit_start:unit_end].strip():
            continue
        if unit_end - unit_start > max_chars:
            if current_start is not None:
                pieces.append(
                    {
                        "char_start": current_start,
                        "char_end": current_end,
                        "overlap_applied": False,
                        "split_reason": "natural_boundary",
                    }
                )
                current_start = current_end = None
            pieces.extend(split_by_characters(unit_start, unit_end, max_chars, overlap_chars))
            continue
        if current_start is None:
            current_start, current_end = unit_start, unit_end
        elif unit_end - current_start <= max_chars:
            current_end = unit_end
        else:
            pieces.append(
                {
                    "char_start": current_start,
                    "char_end": current_end,
                    "overlap_applied": False,
                    "split_reason": "natural_boundary",
                }
            )
            current_start, current_end = unit_start, unit_end
    if current_start is not None:
        pieces.append(
            {
                "char_start": current_start,
                "char_end": current_end,
                "overlap_applied": False,
                "split_reason": "natural_boundary",
            }
        )
    return pieces


def natural_units(content, section):
    units = []
    cursor = section["start"]
    heading_end = section.get("heading_end")
    if heading_end is not None:
        newline = content.find("\n", heading_end, section["end"])
        if newline != -1:
            units.append((section["start"], newline + 1))
            cursor = newline + 1
    block_re = re.compile(r"\n[ \t]*\n")
    for match in block_re.finditer(content, cursor, section["end"]):
        units.append((cursor, match.start() + 1))
        cursor = match.end()
    if cursor < section["end"]:
        units.append((cursor, section["end"]))
    return units


def split_by_characters(start, end, max_chars, overlap_chars):
    pieces = []
    cursor = start
    while cursor < end:
        piece_end = min(cursor + max_chars, end)
        pieces.append(
            {
                "char_start": cursor,
                "char_end": piece_end,
                "overlap_applied": cursor > start,
                "split_reason": "character_limit",
            }
        )
        if piece_end >= end:
            break
        cursor = piece_end - overlap_chars
    return pieces


def refund_rule_version(source_document, rule_refs):
    if rule_refs != ["REFUND-001"]:
        return None
    if source_document.document_code not in {"REFUND-001-V1-SOURCE", "REFUND-001-V2-SOURCE"}:
        return None
    return source_document.version
