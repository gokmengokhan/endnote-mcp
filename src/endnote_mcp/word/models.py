"""Shared defensive OOXML primitives. No Word or EndNote application calls."""
import hashlib
from lxml import etree

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def parse_xml(raw: bytes):
    # Let libxml2 detect the encoding, but never load a DTD or expand entities.
    # Entity declarations require a DTD; reject it before exposing the tree.
    root = etree.fromstring(raw, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True))
    if root.getroottree().docinfo.doctype:
        raise ValueError('DTD/entity declarations are forbidden')
    return root

def text(element) -> str:
    return ''.join(n.text or '' for n in element.iter(W+'t'))

def field_structure(document):
    """Return protected complex-field nodes; reject malformed field phases.

    Instruction/data are accepted only within a complex field's instruction
    phase. Generic code-only fields may omit a separator; actual EndNote
    citation fields require a separator and stored result phase.
    """
    stack = []
    protected = set()
    for node in document.iter():
        if node.tag == W+'fldChar':
            kind = node.get(W+'fldCharType')
            if kind == 'begin':
                stack.append({'separated':False, 'instruction':[]})
            elif kind == 'separate':
                if not stack or stack[-1]['separated']: raise ValueError('Unexpected field separator')
                stack[-1]['separated'] = True
            elif kind == 'end':
                if not stack: raise ValueError('Unexpected field end')
                if not stack[-1]['separated'] and 'EN.JS.CITE' in ''.join(stack[-1]['instruction']):
                    raise ValueError('EndNote citation field missing separator')
                protected.add(node)
                stack.pop()
            else:
                raise ValueError('Unknown field character type')
        elif node.tag in (W+'instrText', W+'fldData'):
            if not stack or stack[-1]['separated']:
                raise ValueError('Instruction/payload outside field instruction phase')
            if node.tag == W+'instrText':
                stack[-1]['instruction'].append(node.text or '')
        if stack: protected.add(node)
    if stack: raise ValueError('Truncated/unclosed complex field')
    return protected
