from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from typing import Any


def read_ogg_page(data: bytes, offset: int) -> tuple[dict[str, Any] | None, int]:
    if len(data) < offset + 27:
        return None, offset

    # check magic
    if data[offset : offset + 4] != b"OggS":
        print(f"Invalid magic at offset {offset}: {data[offset : offset + 4]!r}")
        return None, offset

    # parse header
    version = data[offset + 4]
    header_type = data[offset + 5]
    granule_pos = struct.unpack_from("<Q", data, offset + 6)[0]
    serial = struct.unpack_from("<I", data, offset + 14)[0]
    page_seq = struct.unpack_from("<I", data, offset + 18)[0]
    crc = struct.unpack_from("<I", data, offset + 22)[0]
    segment_count = data[offset + 26]

    # read segment table
    seg_table_start = offset + 27
    if len(data) < seg_table_start + segment_count:
        return None, offset

    segment_table = list(data[seg_table_start : seg_table_start + segment_count])
    body_size = sum(segment_table)

    # read body
    body_start = seg_table_start + segment_count
    if len(data) < body_start + body_size:
        return None, offset

    body = data[body_start : body_start + body_size]

    # parse flags
    flags: list[str] = []
    if header_type & 0x01:
        flags.append("continuation")
    if header_type & 0x02:
        flags.append("BOS")
    if header_type & 0x04:
        flags.append("EOS")

    page = {
        "offset": offset,
        "version": version,
        "header_type": header_type,
        "flags": flags,
        "granule_pos": granule_pos,
        "serial": serial,
        "page_seq": page_seq,
        "crc": crc,
        "segment_count": segment_count,
        "segment_table": segment_table,
        "body_size": body_size,
        "body": body,
        "total_size": 27 + segment_count + body_size,
    }

    return page, body_start + body_size


def parse_opus_head(data: bytes) -> dict[str, Any] | None:
    if len(data) < 19 or data[:8] != b"OpusHead":
        return None

    return {
        "magic": data[:8].decode("ascii"),
        "version": data[8],
        "channels": data[9],
        "pre_skip": struct.unpack_from("<H", data, 10)[0],
        "sample_rate": struct.unpack_from("<I", data, 12)[0],
        "output_gain": struct.unpack_from("<h", data, 16)[0],
        "channel_mapping": data[18],
    }


def parse_opus_tags(data: bytes) -> dict[str, Any] | None:
    if len(data) < 16 or data[:8] != b"OpusTags":
        return None

    offset = 8
    vendor_len = struct.unpack_from("<I", data, offset)[0]
    offset += 4

    if len(data) < offset + vendor_len:
        return None

    vendor = data[offset : offset + vendor_len].decode("utf-8", errors="replace")
    offset += vendor_len

    if len(data) < offset + 4:
        return {"magic": "OpusTags", "vendor": vendor, "comments": []}

    comment_count = struct.unpack_from("<I", data, offset)[0]
    offset += 4

    comments: list[str] = []
    for _ in range(comment_count):
        if len(data) < offset + 4:
            break
        comment_len = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if len(data) < offset + comment_len:
            break
        comment = data[offset : offset + comment_len].decode("utf-8", errors="replace")
        comments.append(comment)
        offset += comment_len

    return {
        "magic": "OpusTags",
        "vendor": vendor,
        "comment_count": comment_count,
        "comments": comments,
    }


def print_table(title: str, rows: list[tuple[str, str]]) -> None:
    if not rows:
        return

    max_key = max(len(r[0]) for r in rows)
    max_val = max(len(str(r[1])) for r in rows)

    border = "+" + "-" * (max_key + 2) + "+" + "-" * (max_val + 2) + "+"
    print(f"\n{title}")
    print(border)
    for key, val in rows:
        print(f"| {key:<{max_key}} | {val!s:<{max_val}} |")
    print(border)


def print_hex_dump(data: bytes, max_bytes: int = 64) -> None:
    print(f"\nHex dump (first {min(len(data), max_bytes)} bytes):")
    for i in range(0, min(len(data), max_bytes), 16):
        hex_part = " ".join(f"{b:02X}" for b in data[i : i + 16])
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in data[i : i + 16])
        print(f"  {i:04X}: {hex_part:<48} |{ascii_part}|")


def inspect_ogg_file(filepath: str) -> None:
    path = Path(filepath)
    if not path.exists():
        print(f"File not found: {filepath}")
        return

    data = path.read_bytes()
    print(f"File: {filepath}")
    print(f"Size: {len(data)} bytes")

    offset = 0
    page_num = 0

    while offset < len(data):
        page, next_offset = read_ogg_page(data, offset)
        if page is None:
            break

        # page header table
        rows: list[tuple[str, Any]] = [
            ("Page Number", page_num),
            ("File Offset", f"0x{page['offset']:X} ({page['offset']})"),
            ("Version", page["version"]),
            ("Header Type", f"0x{page['header_type']:02X}"),
            ("Flags", ", ".join(page["flags"]) if page["flags"] else "(none)"),
            ("Granule Position", page["granule_pos"]),
            ("Serial Number", f"0x{page['serial']:08X}"),
            ("Page Sequence", page["page_seq"]),
            ("CRC", f"0x{page['crc']:08X}"),
            ("Segment Count", page["segment_count"]),
            ("Body Size", f"{page['body_size']} bytes"),
            ("Total Page Size", f"{page['total_size']} bytes"),
        ]
        print_table(f"=== OGG PAGE {page_num} ===", rows)

        # segment table
        if page["segment_count"] <= 16:
            seg_str = ", ".join(str(s) for s in page["segment_table"])
            print(f"\nSegment Table: [{seg_str}]")
        else:
            print(
                f"\nSegment Table: [{page['segment_count']} segments, sum={page['body_size']}]"
            )

        # parse opus headers
        body = page["body"]
        if body[:8] == b"OpusHead":
            opus_head = parse_opus_head(body)
            if opus_head:
                rows = [
                    ("Magic", opus_head["magic"]),
                    ("Version", opus_head["version"]),
                    ("Channels", opus_head["channels"]),
                    ("Pre-skip", f"{opus_head['pre_skip']} samples"),
                    ("Sample Rate", f"{opus_head['sample_rate']} Hz"),
                    ("Output Gain", f"{opus_head['output_gain'] / 256:.2f} dB"),
                    ("Channel Mapping", opus_head["channel_mapping"]),
                ]
                print_table("OpusHead Packet", rows)

        elif body[:8] == b"OpusTags":
            opus_tags = parse_opus_tags(body)
            if opus_tags:
                rows = [
                    ("Magic", opus_tags["magic"]),
                    ("Vendor", opus_tags["vendor"]),
                    ("Comment Count", opus_tags.get("comment_count", 0)),
                ]
                for i, comment in enumerate(opus_tags.get("comments", [])):
                    rows.append(
                        (
                            f"Comment {i + 1}",
                            comment[:60] + ("..." if len(comment) > 60 else ""),
                        )
                    )
                print_table("OpusTags Packet", rows)

        else:
            # audio data page
            print(f"\nAudio data: {len(body)} bytes")
            if page_num < 3:
                print_hex_dump(body, 32)

        offset = next_offset
        page_num += 1

        # limit output for large files
        if page_num >= 5:
            remaining = 0
            temp_offset = offset
            while temp_offset < len(data):
                _, temp_offset = read_ogg_page(data, temp_offset)
                if _ is None:
                    break
                remaining += 1
            if remaining > 0:
                print(f"\n... {remaining} more pages not shown ...")
            break

    print(f"\nTotal pages read: {page_num}")


def inspect_ogg_file_json(filepath: str, max_pages: int = 10) -> dict[str, Any]:
    path = Path(filepath)
    if not path.exists():
        return {"error": f"File not found: {filepath}"}

    data = path.read_bytes()
    result: dict[str, Any] = {
        "file": filepath,
        "size_bytes": len(data),
        "pages": [],
        "summary": {
            "total_pages": 0,
            "has_opus_head": False,
            "has_opus_tags": False,
            "opus_head": None,
            "opus_tags": None,
        },
    }

    offset = 0
    page_num = 0

    while offset < len(data) and page_num < max_pages:
        page, next_offset = read_ogg_page(data, offset)
        if page is None:
            break

        page_info = {
            "page_number": page_num,
            "offset": page["offset"],
            "offset_hex": f"0x{page['offset']:X}",
            "version": page["version"],
            "header_type": page["header_type"],
            "header_type_hex": f"0x{page['header_type']:02X}",
            "flags": page["flags"],
            "is_bos": bool(page["header_type"] & 0x02),
            "is_eos": bool(page["header_type"] & 0x04),
            "is_continuation": bool(page["header_type"] & 0x01),
            "granule_position": page["granule_pos"],
            "serial_number": page["serial"],
            "serial_number_hex": f"0x{page['serial']:08X}",
            "page_sequence": page["page_seq"],
            "crc": page["crc"],
            "crc_hex": f"0x{page['crc']:08X}",
            "segment_count": page["segment_count"],
            "segment_table": page["segment_table"],
            "body_size": page["body_size"],
            "total_page_size": page["total_size"],
            "body_hex_preview": page["body"][:32].hex(" ").upper(),
            "packet_type": None,
            "packet_data": None,
        }

        # parse opus packets
        body = page["body"]
        if body[:8] == b"OpusHead":
            opus_head = parse_opus_head(body)
            if opus_head:
                page_info["packet_type"] = "OpusHead"
                page_info["packet_data"] = opus_head
                result["summary"]["has_opus_head"] = True
                result["summary"]["opus_head"] = opus_head

        elif body[:8] == b"OpusTags":
            opus_tags = parse_opus_tags(body)
            if opus_tags:
                page_info["packet_type"] = "OpusTags"
                page_info["packet_data"] = opus_tags
                result["summary"]["has_opus_tags"] = True
                result["summary"]["opus_tags"] = opus_tags

        else:
            page_info["packet_type"] = "audio_data"

        result["pages"].append(page_info)
        offset = next_offset
        page_num += 1

    # count remaining pages
    remaining = 0
    temp_offset = offset
    while temp_offset < len(data):
        temp_page, temp_offset = read_ogg_page(data, temp_offset)
        if temp_page is None:
            break
        remaining += 1

    result["summary"]["total_pages"] = page_num + remaining
    result["summary"]["pages_shown"] = page_num
    result["summary"]["pages_remaining"] = remaining

    return result


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: ogg_inspect.py <file.ogg> [--json]")
        sys.exit(1)

    use_json = "--json" in sys.argv
    filepath = [arg for arg in sys.argv[1:] if not arg.startswith("--")]

    if not filepath:
        print("Error: No file specified")
        sys.exit(1)

    if use_json:
        result = inspect_ogg_file_json(filepath[0])
        print(json.dumps(result, indent=2))
    else:
        inspect_ogg_file(filepath[0])


if __name__ == "__main__":
    main()
