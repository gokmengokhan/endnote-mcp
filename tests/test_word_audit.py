import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest
import pytest
from zipfile import ZipFile

from endnote_mcp.word import audit as m
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def payload(n=7, label=1, db='fictional', doi='10.1234/example'):
    return base64.b64encode(f'<EndNote><Cite><RecNum>{n}</RecNum><IDText>manuscript-ref-{label}</IDText><record><rec-number>{n}</rec-number><foreign-keys><key app="EN" db-id="{db}">{n}</key></foreign-keys><electronic-resource-num>{doi}</electronic-resource-num></record></Cite></EndNote>'.encode()).decode()


def field(data=None, nested=False):
    result='<w:r><w:rPr><w:rStyle w:val="Derived"/></w:rPr><w:t>1</w:t></w:r>'
    if nested: result='<w:r><w:fldChar w:fldCharType="begin"/><w:instrText> REF bookmark </w:instrText><w:fldChar w:fldCharType="separate"/></w:r>'+result+'<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    return '<w:p><w:r><w:fldChar w:fldCharType="begin"><w:fldData>'+ (payload() if data is None else data)+'</w:fldData></w:fldChar><w:instrText> ADDIN EN.</w:instrText></w:r></w:p><w:p><w:r><w:instrText>JS.CITE </w:instrText><w:fldChar w:fldCharType="separate"/></w:r>'+result+'<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'


class EndNoteAuditTests(unittest.TestCase):
    def audit(self, body, **kw):
        bib='<w:sdt><w:sdtPr><w:tag w:val="EndNote.ReferenceList"/></w:sdtPr><w:sdtContent><w:p><w:r><w:t>[1] Fictional reference</w:t></w:r></w:p></w:sdtContent></w:sdt>'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.docx'
            with ZipFile(p,'w') as z:
                z.writestr('word/document.xml',f'<w:document xmlns:w="{W}"><w:body>{body}{bib}</w:body></w:document>')
                z.writestr('word/styles.xml',f'<w:styles xmlns:w="{W}"><w:style w:styleId="Base"><w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style><w:style w:styleId="Derived"><w:basedOn w:val="Base"/></w:style></w:styles>')
                z.writestr('word/settings.xml',f'<w:settings xmlns:w="{W}"><w:trackRevisions/></w:settings>')
            return m.audit_document(p, **kw)
    def test_cross_paragraph_split_instruction_nested_style_repeat(self):
        r=self.audit(field(nested=True)+field(),expected_groups=[[7],[7]])
        self.assertTrue(r['passed'],r['errors']);self.assertTrue(r['track_changes']);self.assertEqual(len(r['identities']),1)
    def test_unrelated_code_only_complex_field(self):
        r=self.audit(field()+'<w:p><w:r><w:fldChar w:fldCharType="begin"/><w:instrText> DATE </w:instrText><w:fldChar w:fldCharType="end"/></w:r></w:p>')
        self.assertTrue(r['passed'],r['errors'])
    def test_endnote_code_only_field_missing_separator(self):
        r=self.audit(field().replace('<w:fldChar w:fldCharType="separate"/>',''))
        self.assertFalse(r['passed'])
        self.assertTrue(any('separator' in e for e in r['errors']))
    def test_unrelated_simple_field(self):
        r=self.audit(field()+'<w:p><w:fldSimple w:instr="PAGE"><w:r><w:t>2</w:t></w:r></w:fldSimple></w:p>')
        self.assertTrue(r['passed'],r['errors'])
    def test_legacy_field_unqualified(self):
        self.assertFalse(self.audit(field().replace('JS.CITE','CITE'))['passed'])
    def test_compressed_group(self):
        raw=b'<EndNote>'+b''.join(base64.b64decode(payload(n=n,label=i))[9:-10] for i,n in enumerate((7,8,9),1))+b'</EndNote>'
        body=field(base64.b64encode(raw).decode()).replace('<w:t>1</w:t>','<w:t>1-3</w:t>')
        # Add two bibliography entries to the fixture's single control.
        r=self.audit(body)
        self.assertEqual(r['groups'][0]['native_record_ids'],[7,8,9])
        self.assertFalse(any('displayed numbering' in e for e in r['errors']))
    def test_orphan_bibliography(self):
        self.assertFalse(self.audit('')['passed'])
    def test_malformed_payload_root(self):
        self.assertFalse(self.audit(field(base64.b64encode(b'<Other/>').decode()))['passed'])
    def test_unknown_library_not_verified(self):
        self.assertFalse(self.audit(field())['library_identity_verified'])
    def test_malformed_additional_en_key_is_structured_failure(self):
        raw=base64.b64decode(payload()).replace(b'</foreign-keys>',b'<key app="EN">999</key></foreign-keys>')
        r=self.audit(field(base64.b64encode(raw).decode()))
        self.assertFalse(r['passed'])
        self.assertTrue(any('Invalid citation payload' in e for e in r['errors']))
    def test_wrong_database(self):
        r=self.audit(field(),record_map={'database_id':'wrong','records':[{'native_record_id':7,'manuscript_reference':1}]})
        self.assertFalse(r['passed'])
    def test_mixed_database(self):
        self.assertFalse(self.audit(field()+field(payload(n=8,db='other')))['passed'])
    def test_author_date_no_numeric_inference(self):
        r=self.audit(field().replace('<w:t>1</w:t>','<w:t>Smith, 2020</w:t>'),numbering_mode='author-date')
        self.assertTrue(r['passed'],r['errors'])
        self.assertFalse(r['numeric_order_verified'])
    def test_native_terminal_null(self):
        data=base64.b64encode(base64.b64decode(payload())+b"\x00").decode()
        self.assertTrue(self.audit(field(data))["passed"])
    def test_embedded_null_rejected(self):
        data=base64.b64encode(base64.b64decode(payload()).replace(b"<Cite>",b"<Cite>\x00")).decode()
        self.assertFalse(self.audit(field(data))["passed"])
    def test_invalid_base64(self):
        self.assertFalse(self.audit(field('%%%'))['passed'])
    def test_truncation(self):
        self.assertIn('Truncated/unclosed complex field',self.audit(field().replace('<w:fldChar w:fldCharType="end"/>',''))['errors'])
    def test_missing_separator(self):
        self.assertFalse(self.audit(field().replace('<w:fldChar w:fldCharType="separate"/>',''))['passed'])
    def test_repeat_group_order_matters(self):
        self.assertIn('Native citation groups/order differ from expected',self.audit(field()+field(),expected_groups=[[7]])['errors'])
    def test_stale_display_after_moving_native_field(self):
        moved=field(payload(n=8,label=2)).replace('<w:t>1</w:t>','<w:t>2</w:t>')
        r=self.audit(moved+field(),expected_groups=[[8],[7]])
        self.assertIn('Citation group 1: displayed numbering differs from first-citation order',r['errors'])
        self.assertIn('Citation group 2: displayed numbering differs from first-citation order',r['errors'])
    def test_invalid_numeric_display(self):
        for text in ('','1,1','0','1-10001','2-1','one'):
            with self.subTest(text=text):
                r=self.audit(field().replace('<w:t>1</w:t>',f'<w:t>{text}</w:t>'))
                self.assertFalse(r['passed'])
    def test_grouped_and_range_display_parser(self):
        for text,expected in [('1',[1]),('1, 3',[1,3]),('1-3',[1,2,3]),('1\u20133, 5',[1,2,3,5])]:
            with self.subTest(text=text):
                self.assertEqual(m.citation_numbers(text),expected)
        self.assertIsNone(m.citation_numbers('1-2-3'))
    def test_oversized_display_fails_without_exception(self):
        r=self.audit(field().replace('<w:t>1</w:t>','<w:t>'+('1'*5000)+'</w:t>'))
        self.assertIn('Citation group 1: displayed numbering differs from first-citation order',r['errors'])
    def test_missing_identity(self):
        mapping={'records':[{'native_record_id':7,'manuscript_reference':1,'doi':'10.1234/example'},{'native_record_id':8,'manuscript_reference':2,'doi':''}]}
        self.assertIn('Missing or unexpected native reference identities',self.audit(field(),record_map=mapping)['errors'])
    def test_doi_mismatch(self):
        mapping={'records':[{'native_record_id':7,'manuscript_reference':1,'doi':'10.1234/wrong'}]}
        self.assertIn('Record 7: DOI mismatch',self.audit(field(),record_map=mapping)['errors'])
    def test_repeated_database_identity_mismatch(self):
        self.assertFalse(self.audit(field()+field(payload(db='other')))['passed'])
    def test_dtd_payload_rejected(self):
        data=base64.b64encode(b'<!DOCTYPE EndNote [<!ENTITY x "bad">]><EndNote/>').decode()
        self.assertFalse(self.audit(field(data))['passed'])
    def test_baseline_override_beats_inherited_superscript(self):
        f=field().replace('<w:rStyle w:val="Derived"/>','<w:rStyle w:val="Derived"/><w:vertAlign w:val="baseline"/>')
        self.assertIn('Citation result is not entirely superscript',self.audit(f)['errors'])
    def test_unresolved_revisions_placeholder(self):
        r=self.audit(field()+'<w:p><w:ins><w:r><w:t>{Author, 2020 #7}</w:t></w:r></w:ins></w:p>')
        self.assertFalse(r['passed']);self.assertTrue(r['placeholders']);self.assertTrue(r['unresolved_revisions'])


if __name__=='__main__':unittest.main()


def test_audit_uses_hashed_snapshot(tmp_path, monkeypatch):
    import hashlib
    source=tmp_path/'snapshot.docx'
    original=b'not-a-zip snapshot A'
    source.write_bytes(original)
    actual_zip=m.ZipFile
    def replace_before_open(target, *args, **kwargs):
        with actual_zip(source,'w') as z:
            z.writestr('word/document.xml',f'<w:document xmlns:w="{W}"><w:body/></w:document>')
        return actual_zip(target,*args,**kwargs)
    monkeypatch.setattr(m,'ZipFile',replace_before_open)
    result=m.audit_document(source)
    assert result['docx_sha256']==hashlib.sha256(original).hexdigest()
    assert any('zip' in error.lower() for error in result['errors'])


@pytest.mark.parametrize('record_id',[0,-1])
def test_nonpositive_payload_identity_without_optional_expectations(record_id):
    result=EndNoteAuditTests().audit(field(payload(n=record_id)))
    assert not result['passed']
    assert any('Invalid citation payload' in error and 'positive' in error for error in result['errors'])
    assert result['groups'][0]['native_record_ids']==[]
    assert result['identities']==[]


@pytest.mark.parametrize('encoding',['utf-8','utf-16-le','utf-16-be','iso-8859-1'])
@pytest.mark.parametrize('part',['document','styles','settings'])
@pytest.mark.parametrize('declaration_kind',['none','dtd','entity'])
def test_audit_encoded_xml_declarations(tmp_path,encoding,part,declaration_kind):
    bib='<w:sdt><w:sdtPr><w:tag w:val="EndNote.ReferenceList"/></w:sdtPr><w:sdtContent><w:p><w:r><w:t>1 Fictional reference</w:t></w:r></w:p></w:sdtContent></w:sdt>'
    parts={
        'document':f'<w:document xmlns:w="{W}"><w:body>{field()}{bib}</w:body></w:document>',
        'styles':f'<w:styles xmlns:w="{W}"><w:style w:styleId="Derived"><w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style></w:styles>',
        'settings':f'<w:settings xmlns:w="{W}"><w:trackRevisions/></w:settings>',
    }
    declaration=''
    if declaration_kind=='dtd': declaration=f'<!DOCTYPE w:{part}>'
    if declaration_kind=='entity':
        declaration=f'<!DOCTYPE w:{part} [<!ENTITY injected "Fictional reference">]>'
        if part=='document': parts[part]=parts[part].replace('Fictional reference','&injected;')
    xml_encoding='UTF-16' if encoding.startswith('utf-16') else encoding
    parts[part]=('<?xml version="1.0" encoding="'+xml_encoding+'"?>'+declaration+parts[part]).encode(encoding)
    if encoding=='utf-16-le': parts[part]=b'\xff\xfe'+parts[part]
    if encoding=='utf-16-be': parts[part]=b'\xfe\xff'+parts[part]
    source=tmp_path/'encoded.docx'
    with ZipFile(source,'w') as z:
        for name,content in parts.items(): z.writestr('word/'+name+'.xml',content)
    original=source.read_bytes()
    result=m.audit_document(source)
    if declaration_kind=='none':
        assert result['passed'],result['errors']
    else:
        assert not result['passed']
        assert any('DTD/entity declarations are forbidden' in error for error in result['errors'])
        assert result['bibliography']==[]
    assert source.read_bytes()==original
