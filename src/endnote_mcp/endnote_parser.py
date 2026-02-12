"""Parse an EndNote XML export file using lxml iterparse.

EndNote exports XML with a structure like:

  <xml><records>
    <record>
      <rec-number>1</rec-number>
      <ref-type name="Journal Article">17</ref-type>
      <contributors><authors><author><style ...>Smith, J.</style></author>...</authors></contributors>
      <titles><title><style ...>Some Title</style></title>
        <secondary-title><style ...>Journal Name</style></secondary-title></titles>
      <dates><year><style ...>2020</style></year></dates>
      <keywords><keyword><style ...>keyword1</style></keyword>...</keywords>
      <abstract><style ...>Abstract text</style></abstract>
      <urls><related-urls><url><style ...>https://...</style></url></related-urls>
        <pdf-urls><url><style ...>internal-pdf://...</style></url></pdf-urls></urls>
      ...
    </record>
  </records></xml>

We use iterparse to avoid loading the entire file into memory.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Generator

from lxml import etree


def _text(el: etree._Element | None) -> str:
    """Extract all text content from an element and its children."""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _find_text(record: etree._Element, xpath: str) -> str:
    """Find first matching element and extract its text."""
    el = record.find(xpath)
    return _text(el)


def _find_all_text(record: etree._Element, xpath: str) -> list[str]:
    """Find all matching elements and extract their text."""
    return [_text(el) for el in record.findall(xpath) if _text(el)]


def _extract_pdf_filename(record: etree._Element) -> str:
    """Extract the PDF filename from internal-pdf:// URLs."""
    for url_el in record.findall(".//urls/pdf-urls/url"):
        url_text = _text(url_el)
        if url_text.startswith("internal-pdf://"):
            # internal-pdf://filename.pdf or internal-pdf://0123456789/filename.pdf
            path_part = url_text.replace("internal-pdf://", "")
            # Return the last component (the actual filename)
            return path_part.split("/")[-1]
    return ""


def parse_endnote_xml(xml_path: str | Path) -> Generator[dict, None, None]:
    """Yield one dict per <record> in the EndNote XML export.

    Each dict is ready for db.upsert_reference().
    Uses iterparse for constant memory usage regardless of file size.
    """
    xml_path = Path(xml_path)
    context = etree.iterparse(str(xml_path), events=("end",), tag="record")

    for _event, record in context:
        rec_number_text = _find_text(record, "rec-number")
        if not rec_number_text:
            record.clear()
            continue

        try:
            rec_number = int(rec_number_text)
        except ValueError:
            record.clear()
            continue

        # Reference type
        ref_type_el = record.find("ref-type")
        ref_type = ref_type_el.get("name", "") if ref_type_el is not None else ""

        # Authors
        authors = _find_all_text(record, ".//contributors/authors/author")

        # Keywords
        keywords = _find_all_text(record, ".//keywords/keyword")

        # PDF filename
        pdf_filename = _extract_pdf_filename(record)

        ref = {
            "rec_number": rec_number,
            "ref_type": ref_type,
            "title": _find_text(record, ".//titles/title"),
            "authors": json.dumps(authors),
            "year": _find_text(record, ".//dates/year"),
            "journal": _find_text(record, ".//titles/secondary-title"),
            "volume": _find_text(record, ".//volume"),
            "issue": _find_text(record, ".//number"),
            "pages": _find_text(record, ".//pages"),
            "abstract": _find_text(record, ".//abstract"),
            "keywords": json.dumps(keywords),
            "doi": _find_text(record, ".//electronic-resource-num"),
            "url": _find_text(record, ".//urls/related-urls/url"),
            "publisher": _find_text(record, ".//publisher"),
            "place_published": _find_text(record, ".//pub-location"),
            "edition": _find_text(record, ".//edition"),
            "isbn": _find_text(record, ".//isbn"),
            "label": _find_text(record, ".//label"),
            "notes": _find_text(record, ".//notes"),
            "pdf_path": pdf_filename,
        }

        yield ref

        # Free memory
        record.clear()
        while record.getprevious() is not None:
            del record.getparent()[0]
