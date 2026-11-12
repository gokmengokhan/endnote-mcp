#!/usr/bin/env python3
"""Read-only EndNote 25 OOXML field audit; not scientific support or native parity proof.

Example: python3 scripts/docx_endnote_audit.py manuscript.docx --record-map map.json
  --citation-audit citations.json --expected-count 19
Groups may alternatively be a JSON array of arrays of native record IDs (--groups).
Only main-document order is qualified; embedded XML is parsed without entity expansion.
"""
import base64
import binascii
import hashlib
from pathlib import Path
from io import BytesIO
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile
from .models import field_structure

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class _NoDTDTreeBuilder(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        # Called after encoding detection, before any internal entity expansion.
        raise ValueError('DTD/entity declarations are forbidden')


def xml(raw):
    return ET.fromstring(raw, parser=ET.XMLParser(target=_NoDTDTreeBuilder()))


def txt(e):
    return ''.join(n.text or '' for n in e.iter(W+'t'))


def doi(s):
    return re.sub(r'^https?://(?:dx\.)?doi.org/', '', s.strip(), flags=re.I).lower()


def citation_numbers(displayed):
    """Parse bounded first-citation numeric displays; fail closed on malformed ranges."""
    token=r'\d{1,5}(?:\s*[-\u2013]\s*\d{1,5})?'
    if not re.fullmatch(token+r'(?:\s*,\s*'+token+r')*',displayed.strip()):
        return None
    numbers=[]
    for part in displayed.strip().split(','):
        ends=re.split(r'[-\u2013]',part.strip())
        first=int(ends[0]);last=int(ends[-1])
        if first<1 or last<first or last>10000 or len(numbers)+last-first+1>10000:
            return None
        numbers.extend(range(first,last+1))
    return numbers


def audit_document(path: Path, expected_groups=None, record_map=None,
                   numbering_mode="numeric-first-citation") -> dict:
    """Audit saved main-document fields; no native execution or scientific proof.

    Originally ported from the Submissions project's docx_endnote_audit.py.
    record_map = {"database_id": optional string, "records": [
      {"native_record_id": int, "manuscript_reference": int, "doi": optional str}]}
    Author-date mode checks structure/identity without inferring numeric order.
    """
    if numbering_mode not in ("numeric-first-citation", "author-date"):
        raise ValueError("Unsupported numbering_mode")
    expected_count = None
    if record_map is not None:
        if not isinstance(record_map, dict) or not isinstance(record_map.get('records'), list):
            raise ValueError('record_map requires a records list')
        for record in record_map['records']:
            if (not isinstance(record, dict)
                    or type(record.get('native_record_id')) is not int
                    or record['native_record_id'] < 1
                    or type(record.get('manuscript_reference')) is not int
                    or record['manuscript_reference'] < 1
                    or not isinstance(record.get('doi', ''), str)):
                raise ValueError('Invalid record_map identity')
        if 'database_id' in record_map and (not isinstance(record_map['database_id'], str) or not record_map['database_id']):
            raise ValueError('Invalid expected database_id')
    if expected_groups is not None and (not isinstance(expected_groups, list) or any(
            not isinstance(g, list) or not g or any(type(n) is not int or n < 1 for n in g)
            for g in expected_groups)):
        raise ValueError('Invalid expected_groups')
    raw = Path(path).read_bytes()
    result = dict(docx_sha256=hashlib.sha256(raw).hexdigest(), passed=False,
                  groups=[], bibliography=[], identities=[], errors=[],
                  limitations=__doc__, track_changes=False, unresolved_revisions=[], placeholders=[])
    result['numbering_mode'] = numbering_mode
    result['numeric_order_verified'] = False
    result['library_identity_verified'] = False
    errors = result['errors']
    try:
        with ZipFile(BytesIO(raw)) as z:
            if len(z.namelist()) != len(set(z.namelist())):
                raise ValueError('Duplicate ZIP parts')
            doc = xml(z.read('word/document.xml'))
            styles = xml(z.read('word/styles.xml')) if 'word/styles.xml' in z.namelist() else ET.Element('empty')
            settings = xml(z.read('word/settings.xml')) if 'word/settings.xml' in z.namelist() else ET.Element('empty')
    except (BadZipFile, KeyError, ET.ParseError, ValueError) as e:
        errors.append(str(e)); return result
    try:
        field_structure(doc)
    except ValueError as exc:
        errors.append(str(exc))
    style_map = {s.get(W+'styleId'): s for s in styles.iter(W+'style')}
    def style_align(sid, seen=None):
        seen = set() if seen is None else seen
        if not sid or sid in seen or sid not in style_map: return None
        seen.add(sid); s = style_map[sid]
        a = s.find(W+'rPr/'+W+'vertAlign')
        if a is not None: return a.get(W+'val')
        base = s.find(W+'basedOn')
        return style_align(base.get(W+'val'), seen) if base is not None else None
    def align(run, paragraph):
        rp = run.find(W+'rPr') if run is not None else None
        if rp is not None:
            a = rp.find(W+'vertAlign')
            if a is not None: return a.get(W+'val')
            s = rp.find(W+'rStyle')
            v = style_align(s.get(W+'val')) if s is not None else None
            if v: return v
        if paragraph is not None:
            s = paragraph.find(W+'pPr/'+W+'pStyle')
            v = style_align(s.get(W+'val')) if s is not None else None
            if v: return v
        a = styles.find(W+'docDefaults/'+W+'rPrDefault/'+W+'rPr/'+W+'vertAlign')
        return a.get(W+'val') if a is not None else None
    track = settings.find(W+'trackRevisions')
    result['track_changes'] = track is not None and track.get(W+'val', 'true') not in ('0','false','off')
    for e in doc.iter():
        tag = e.tag.removeprefix(W)
        if tag in ('ins','del','moveFrom','moveTo') or tag.endswith('PrChange'):
            result['unresolved_revisions'].append(tag)
    if result['unresolved_revisions']: errors.append('Unresolved revisions: clean derivative required')
    result['placeholders'] = re.findall(r'\{[^{}\n]*#\d+[^{}\n]*\}|\[\[.*?\]\]|AUTHOR TO COMPLETE', txt(doc))
    if result['placeholders']: errors.append('Unresolved temporary citations/placeholders')
    bibs=[]
    for s in doc.iter(W+'sdt'):
        tag=s.find(W+'sdtPr/'+W+'tag')
        if tag is not None and tag.get(W+'val')=='EndNote.ReferenceList': bibs.append(s)
    for s in bibs:
        content=s.find(W+'sdtContent')
        if content is None: errors.append('Empty EndNote bibliography control');continue
        for p in content.iter(W+'p'):
            t=txt(p).strip()
            if t:
                match=re.match(r'^\s*(?:\[(\d+)\]|(\d+)[.)]?)\s*', t)
                result['bibliography'].append({'number':int(next(v for v in match.groups() if v)) if match else None,'text':t})
    if len(bibs)!=1: errors.append('Expected exactly one EndNote.ReferenceList control')
    stack=[]; identities={}
    def finish(f):
        instruction=''.join(f['instruction']).strip()
        if 'EN.JS.CITE' not in instruction:
            if re.search(r'\bEN[.\s]', instruction):
                errors.append('Unqualified legacy/unsupported EndNote field')
            return
        if not f['separated']: errors.append('Citation field missing separator')
        g={'instruction':instruction,'native_record_ids':[],'records':[], 'result':''.join(f['text']),
           'superscript':bool(f['styles']) and all(v=='superscript' for v in f['styles'])}
        result['groups'].append(g)
        if numbering_mode == 'numeric-first-citation' and not g['superscript']: errors.append('Citation result is not entirely superscript')
        if not g['result'].strip(): errors.append('Citation result empty')
        if len(f['data'])!=1: errors.append('Citation needs exactly one fldData payload');return
        try:
            encoded=''.join(f['data'][0].split())
            payload=base64.b64decode(encoded,validate=True)
            payload.decode('utf-8',errors='strict')
            # EndNote 25 may append one C-string terminator to its UTF-8 XML.
            # Accept this observed framing only, never embedded/truncated XML.
            if payload.endswith(b'\x00'): payload=payload[:-1]
            endnote=xml(payload)
            if endnote.tag!='EndNote': raise ValueError('Expected EndNote payload root')
            cites=endnote.findall('Cite')
            if not cites: raise ValueError('EndNote payload contains no Cite')
            for c in cites:
                n=int(c.findtext('RecNum','')); label=c.findtext('IDText','')
                if n < 1: raise ValueError('Native record ID must be positive')
                record=c.find('record')
                if record is None: raise ValueError('Missing embedded record')
                if record.findtext('rec-number')!=str(n): raise ValueError('Embedded record ID mismatch')
                keys=[{'app':k.get('app'),'db_id':k.get('db-id'),'record_id':k.text} for k in record.findall('foreign-keys/key')]
                if any(not k['db_id'] or k['record_id'] != str(n)
                       for k in keys if k['app']=='EN'):
                    raise ValueError('Malformed additional EndNote database identity')
                en=[k for k in keys if k['app']=='EN' and k['db_id'] and k['record_id']==str(n)]
                if len(en)!=1: raise ValueError('Missing/ambiguous EndNote database identity')
                item={'native_record_id':n,'label':label,'foreign_keys':keys,'doi':doi(record.findtext('electronic-resource-num',''))}
                if n in identities and identities[n]!=item: raise ValueError('Inconsistent repeated native identity')
                identities[n]=item;g['native_record_ids'].append(n);g['records'].append(item)
        except (ValueError, UnicodeError, ET.ParseError, binascii.Error) as e: errors.append('Invalid citation payload: '+str(e))
    def walk(e, run=None, paragraph=None):
        if e.tag==W+'p': paragraph=e
        if e.tag==W+'r': run=e
        if e.tag==W+'fldSimple' and 'EN.' in e.get(W+'instr', ''):
            errors.append('Unqualified EndNote simple field')
        if e.tag==W+'fldChar':
            kind=e.get(W+'fldCharType')
            if kind=='begin': stack.append({'instruction':[],'data':[],'text':[],'styles':[],'separated':False})
            elif kind=='separate':
                if not stack or stack[-1]['separated']: errors.append('Unexpected field separator')
                else: stack[-1]['separated']=True
            elif kind=='end':
                if not stack: errors.append('Unexpected field end')
                else: finish(stack.pop())
            else: errors.append('Unknown field character type')
        elif e.tag==W+'fldData':
            if stack: stack[-1]['data'].append(e.text or '')
            else: errors.append('Orphan field data')
        elif e.tag==W+'instrText':
            if not stack or stack[-1]['separated']: errors.append('Instruction outside field instruction phase')
            else: stack[-1]['instruction'].append(e.text or '')
        elif e.tag==W+'t':
            for f in stack:
                if f['separated']:
                    f['text'].append(e.text or '')
                    if (e.text or '').strip(): f['styles'].append(align(run,paragraph))
        for child in e: walk(child,run,paragraph)
    walk(doc)
    if stack: errors.append('Truncated/unclosed complex field')
    if not result['groups']: errors.append('No native EndNote citation groups')
    # first-citation numeric style numbers references by first citation. Moving intact
    # fields changes their order but does not itself refresh their display text.
    numbering={}
    for index,g in enumerate(result['groups'],1):
        for n in g['native_record_ids']:
            if n not in numbering: numbering[n]=len(numbering)+1
        expected_numbers=sorted(numbering[n] for n in g['native_record_ids'])
        displayed=g['result'].strip()
        actual_numbers=citation_numbers(displayed)
        if numbering_mode == 'numeric-first-citation' and (not expected_numbers or actual_numbers is None or sorted(actual_numbers)!=expected_numbers):
            errors.append(f'Citation group {index}: displayed numbering differs from first-citation order')
    result['identities']=list(identities.values())
    databases = {k['db_id'] for item in identities.values() for k in item['foreign_keys'] if k['app']=='EN'}
    result['database_ids'] = sorted(databases)
    if len(databases)>1: errors.append('Mixed EndNote database identities')
    known_database = record_map.get('database_id') if isinstance(record_map, dict) else None
    if known_database and databases != {known_database}: errors.append('EndNote database identity mismatch')
    result['library_identity_verified'] = bool(known_database and databases == {known_database})
    if expected_groups is not None and [g['native_record_ids'] for g in result['groups']]!=expected_groups:
        errors.append('Native citation groups/order differ from expected')
    if record_map is not None:
        records=record_map['records'] if isinstance(record_map,dict) else record_map
        expected={int(v['native_record_id']):v for v in records}
        if len(expected)!=len(records): errors.append('Expected map has duplicate native IDs')
        if len({v['manuscript_reference'] for v in records})!=len(records): errors.append('Expected map has duplicate manuscript references')
        if set(expected)!=set(identities): errors.append('Missing or unexpected native reference identities')
        for n,item in identities.items():
            if n not in expected: continue
            v=expected[n]
            if item['label']!='manuscript-ref-'+str(v['manuscript_reference']): errors.append(f'Record {n}: manuscript label mismatch')
            if v.get('doi') and doi(v['doi'])!=item['doi']: errors.append(f'Record {n}: DOI mismatch')
        if expected_count is None: expected_count=len(records)
    numbers=[v['number'] for v in result['bibliography']]
    if numbering_mode == 'numeric-first-citation' and numbers!=list(range(1,len(numbers)+1)): errors.append('Bibliography numbering is missing, duplicated or unordered')
    if expected_count is not None:
        if len(identities)!=expected_count: errors.append('Unique reference count mismatch')
        if len(result['bibliography'])!=expected_count: errors.append('Bibliography count mismatch')
    elif len(result['bibliography'])!=len(identities): errors.append('Bibliography and unique citation counts differ')
    result['numeric_order_verified'] = numbering_mode == 'numeric-first-citation' and not errors
    result['passed']=not errors
    return result
