"""New-file-only targeted OOXML preparation; temporary tokens are not fields.

Citation-plan JSON schema (all indices zero-based in main-document traversal):
{"source_sha256": "64 lowercase hex characters", "citations": [
 {"paragraph_index": 0, "run_index": 0, "original_text": "[1]",
  "temporary_token": "{Example, 2020 #7}", "database_id": "fictional",
  "native_record_id": 7}], "bibliography_paragraphs": [
 {"paragraph_index": 1, "original_text": "Exact literal paragraph", "remove": true}]}

Each citation anchor identifies exactly one occurrence within a single w:t in
its indexed run. Distinct nonoverlapping spans may share a text node; repeated
authentic single-record tokens are permitted. Each token must contain exactly
one matching #record ID; grouped tokens are unsupported until the plan schema
provides explicit group bindings. All citations must share one database_id, which
is retained with per-anchor record/token bindings in the receipt. Bibliography removal requires exact whole-paragraph text and
explicit remove=true. Paragraphs with section properties or comment/bookmark
attachments cannot be removed. Fields, content controls and human revisions
cannot be edited. Unmodified ZIP part bytes are preserved, including comments and rels.
"""
from pathlib import Path
from io import BytesIO
import re
from zipfile import ZipFile, BadZipFile
from lxml import etree
from .models import W, parse_xml, sha256, text, field_structure


def prepare_conversion(source: Path, destination: Path, plan: dict,
                       expected_sha256: str) -> dict:
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or destination.is_symlink():
        raise ValueError('Symlink paths are not allowed')
    if destination.exists() or source.resolve() == destination.resolve():
        raise ValueError('Destination must be a new file')
    raw = source.read_bytes()
    digest = sha256(raw)
    if not isinstance(plan, dict) or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
        raise ValueError('Invalid hash or plan')
    if digest != expected_sha256 or plan.get('source_sha256') != digest:
        raise ValueError('Source hash mismatch')
    citations = plan.get('citations')
    bibliography = plan.get('bibliography_paragraphs', [])
    if not isinstance(citations, list) or not citations or not isinstance(bibliography, list):
        raise ValueError('Plan requires citation list and bibliography list')
    try:
        with ZipFile(BytesIO(raw)) as z:
            infos = z.infolist()
            if len({i.filename for i in infos}) != len(infos):
                raise ValueError('Duplicate ZIP parts')
            parts = {i.filename: z.read(i) for i in infos}
            archive_comment = z.comment
        doc = parse_xml(parts['word/document.xml'])
    except (BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise ValueError('Invalid DOCX package') from exc
    for e in doc.iter():
        tag = etree.QName(e).localname
        if tag in ('ins', 'del', 'moveFrom', 'moveTo') or tag.endswith('PrChange'):
            raise ValueError('Existing human revisions require reconciliation')
    paragraphs = list(doc.iter(W+'p'))
    field_nodes = field_structure(doc)
    def indexed(items, index):
        if type(index) is not int or index < 0 or index >= len(items):
            raise ValueError('Invalid anchor index')
        return items[index]
    def protected(node):
        return any(e in field_nodes or e.tag in (W+'fldSimple', W+'sdt')
                   for e in list(node.iter()) + list(node.iterancestors()))
    changes = []
    occupied = {}
    database_id = None
    bindings = []
    for c in citations:
        if not isinstance(c, dict): raise ValueError('Invalid citation anchor')
        p = indexed(paragraphs, c.get('paragraph_index'))
        run = indexed(list(p.iter(W+'r')), c.get('run_index'))
        original, token = c.get('original_text'), c.get('temporary_token')
        if (not isinstance(original, str) or not original or not isinstance(token, str)
                or not token or type(c.get('native_record_id')) is not int
                or c['native_record_id'] < 1 or not isinstance(c.get('database_id'), str)
                or not c['database_id']):
            raise ValueError('Incomplete citation identity or text')
        if not re.fullmatch(r'\{[^{}#;\r\n]*#' + str(c['native_record_id']) + r'\}', token):
            raise ValueError('Temporary token must contain one matching native record identity; groups are unsupported')
        if database_id is None: database_id = c['database_id']
        if c['database_id'] != database_id:
            raise ValueError('Mixed database scope is unsupported')
        bindings.append({key:c[key] for key in ('database_id', 'native_record_id',
                        'temporary_token', 'paragraph_index', 'run_index')})
        if protected(run): raise ValueError('Citation anchor overlaps field or content control')
        nodes = list(run.iter(W+'t'))
        matches = [(n, (n.text or '').count(original)) for n in nodes]
        if sum(count for _, count in matches) != 1:
            raise ValueError('Missing or ambiguous citation anchor')
        node = next(n for n, count in matches if count)
        start = node.text.index(original)
        end = start + len(original)
        spans = occupied.setdefault(node, [])
        if any(start < right and end > left for left, right, _ in spans):
            raise ValueError('Duplicate/overlapping citation anchors')
        spans.append((start, end, token))
        changes.append((node, start, end, token))
    removals = []
    attachment_tags = {W+name for name in (
        'sectPr', 'bookmarkStart', 'bookmarkEnd', 'commentRangeStart',
        'commentRangeEnd', 'commentReference')}
    for b in bibliography:
        if not isinstance(b, dict) or b.get('remove') is not True:
            raise ValueError('Bibliography removal requires explicit authorization')
        p = indexed(paragraphs, b.get('paragraph_index'))
        if (not b.get('original_text') or text(p) != b['original_text']
                or p in removals or protected(p)
                or any(n.tag in attachment_tags for n in p.iter())
                or any(n in occupied for n in p.iter())):
            raise ValueError('Ambiguous or protected bibliography paragraph')
        removals.append(p)
    for node, spans in occupied.items():
        value = node.text
        for start, end, token in sorted(spans, reverse=True):
            value = value[:start] + token + value[end:]
        node.text = value
    for p in removals: p.getparent().remove(p)
    parts['word/document.xml'] = etree.tostring(doc, encoding='UTF-8', xml_declaration=True)
    # Recheck source just before creating output. Exclusive creation also rejects
    # another process creating the destination after preflight.
    if sha256(source.read_bytes()) != digest: raise ValueError('Source changed during preparation')
    created = False
    try:
        with destination.open('xb') as output:
            created = True
            with ZipFile(output, 'w') as z:
                z.comment = archive_comment
                for info in infos: z.writestr(info, parts[info.filename])
    except FileExistsError as exc:
        raise ValueError('Destination must be a new file') from exc
    except BaseException:
        if created: destination.unlink(missing_ok=True)
        raise
    return {'stage':'prepared', 'status':'prepared', 'source_sha256':digest,
            'destination_sha256':sha256(destination.read_bytes()),
            'native_fields_created':False, 'citation_count':len(changes),
            'database_id':database_id, 'citation_bindings':bindings,
            'bibliography_paragraphs_removed':len(removals),
            'limitations':['Temporary citations only; native conversion has not run.']}
