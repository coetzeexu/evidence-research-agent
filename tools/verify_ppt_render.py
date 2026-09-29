"""Audit Poppler pdftotext -bbox-layout output from a rendered PPT PDF.

Usage: pdftotext -bbox-layout report.pdf bounds.html
       uv run python tools/verify_ppt_render.py bounds.html
This detects intersecting word boxes, not every possible visual/layout defect.
"""

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def audit(path):
    namespace = {"h": "http://www.w3.org/1999/xhtml"}
    pages = ET.parse(path).findall(".//h:page", namespace)
    overlaps, outside = [], []
    count = 0
    for index, page in enumerate(pages, 1):
        words = page.findall(".//h:word", namespace)
        count += len(words)
        boxes = [tuple(float(w.get(k)) for k in ("xMin", "yMin", "xMax", "yMax")) for w in words]
        for j, a in enumerate(boxes):
            if a[0] < 0 or a[1] < 0 or a[2] > float(page.get("width")) or a[3] > float(page.get("height")):
                outside.append({"page": index, "word": words[j].text})
            for k, b in enumerate(boxes[j + 1 :], j + 1):
                if min(a[2], b[2]) - max(a[0], b[0]) > 0.5 and min(a[3], b[3]) - max(a[1], b[1]) > 0.5:
                    overlaps.append({"page": index, "words": [words[j].text, words[k].text]})
    return {
        "pages": len(pages),
        "words": count,
        "overlaps": overlaps,
        "out_of_page": outside,
        "passed": bool(count) and not overlaps and not outside,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bounds", type=Path)
    args = parser.parse_args()
    result = audit(args.bounds)
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)
