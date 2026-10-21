"""Portable MCP adapters. No native application backend is shipped."""
from __future__ import annotations
import json
import platform
from pathlib import Path
from yaml import YAMLError
from endnote_mcp.config import Config
from .audit import audit_document
from .prepare import prepare_conversion

LIMITATIONS = ['No native conversion has run; no native comparison or submission readiness is established.']


def _error(stage, code='invalid_request'):
    # Never echo parser exceptions, document text, or client-supplied paths.
    return {'stage': stage, 'status': 'error', 'error_code': code,
            'limitations': LIMITATIONS.copy()}


def get_word_endnote_status() -> dict:
    """Report shipped capabilities only; does not inspect or launch applications."""
    try:
        requested = Config.load().native_word_enabled
    except (OSError, ValueError, TypeError, KeyError, YAMLError):
        requested = None
    return {'native_word_requested': requested, 'native_word_effective': False,
            'configuration_note': 'Native enable requests cannot activate the absent, unqualified backend.',
            'stage': 'capability', 'status': 'unqualified',
            'platform': platform.system(), 'native_backend_shipped': False,
            'native_update_available': False, 'applications_inspected': False,
            'application_versions': None, 'addin_status': 'unknown',
            'limitations': LIMITATIONS.copy()}


def _absolute(path: str) -> Path:
    value = Path(path)
    if not value.is_absolute():
        raise ValueError('Absolute path required')
    # Reject symlinks at every component, before canonicalization.
    if any(p.is_symlink() for p in (value, *value.parents)):
        raise ValueError('Symlink path forbidden')
    return value


def audit_word_endnote_document(docx_path: str,
        expected_groups: list[list[int]] | None = None,
        record_map_path: str | None = None,
        numbering_mode: str = 'numeric-first-citation') -> dict:
    """Audit a saved DOCX package without calling Word or EndNote."""
    try:
        path = _absolute(docx_path)
        record_map = json.loads(_absolute(record_map_path).read_text('utf-8')) if record_map_path else None
        result = audit_document(path, expected_groups, record_map, numbering_mode)
        result.update(stage='audited', status='passed' if result['passed'] else 'failed')
        prior = result.get('limitations', [])
        result['limitations'] = ([prior] if isinstance(prior, str) else list(prior)) + LIMITATIONS
        return result
    except (OSError, ValueError, TypeError, KeyError, YAMLError):
        return _error('audit')


def prepare_word_endnote_conversion(source_path: str, destination_path: str,
        citation_plan_path: str, expected_source_sha256: str, *, config: Config) -> dict:
    """Prepare temporary citations in a new file inside an explicit working root."""
    if config.native_working_root is None:
        return {'stage': 'preflight', 'status': 'blocked',
                'error_code': 'working_root_required', 'limitations': LIMITATIONS.copy()}
    try:
        root = _absolute(str(config.native_working_root)).resolve(strict=True)
        source = _absolute(source_path)
        destination = _absolute(destination_path)
        plan_path = _absolute(citation_plan_path)
        canonical = destination.resolve()
        if (not root.is_dir() or not canonical.is_relative_to(root)
                or canonical == root or destination.exists()
                or canonical == source.resolve()
                or canonical == plan_path.resolve()):
            raise ValueError('Invalid destination')
        # Finder aliases are regular files and cannot serve as directory ancestors;
        # existing destination files are rejected irrespective of their type.
        if not destination.parent.is_dir():
            raise ValueError('Missing parent')
        plan = json.loads(plan_path.read_text('utf-8'))
        result = prepare_conversion(source, destination, plan, expected_source_sha256)
        result['limitations'].extend(LIMITATIONS)
        return result
    except (OSError, ValueError, TypeError, KeyError, YAMLError):
        return _error('preparation')


def register_tools(server, get_config):
    server.tool()(get_word_endnote_status)
    server.tool()(audit_word_endnote_document)

    @server.tool()
    def prepare_word_endnote_conversion(source_path: str, destination_path: str,
            citation_plan_path: str, expected_source_sha256: str) -> dict:
        """Create a new temporary-citation copy; requires configured native_working_root."""
        try:
            config = get_config()
        except (OSError, ValueError, TypeError, KeyError, YAMLError):
            return _error('preflight', 'configuration_unavailable')
        return globals()['prepare_word_endnote_conversion'](
            source_path, destination_path, citation_plan_path,
            expected_source_sha256, config=config)
