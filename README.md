# EndNote MCP

Connect your EndNote reference library to Claude AI. Search references, read PDFs, and format citations — all directly in Claude Desktop conversations.

## What It Does

Once set up, you can ask Claude things like:

- *"Search my library for social capital and Bourdieu"*
- *"Find papers that discuss grounded theory methodology"*
- *"Give me the APA citation for reference #1234"*
- *"Read pages 5-7 from that Smith et al. paper"*
- *"List all my references about inequality from 2015-2023"*

Claude searches your **local** library — nothing is uploaded to the cloud beyond the normal conversation.

## How It Works

```
EndNote Library → XML Export → endnote-mcp index → SQLite Database (FTS5)
                                                          ↕
                                   Claude Desktop ← MCP Server
```

Your references and PDF text are indexed into a local SQLite database with full-text search. Claude connects to it through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

## Requirements

- **EndNote 20 or 21** (any edition)
- **Claude Desktop** app
- **Python 3.10+**
- **uv** (recommended) or pip

## Quick Start

### 1. Install

```bash
# With uv (recommended)
uv tool install endnote-mcp

# Or with pip
pip install endnote-mcp
```

### 2. Export your library from EndNote

In EndNote: **File → Export** → choose **XML** format → save to a convenient location (e.g., Desktop).

### 3. Run the setup wizard

```bash
endnote-mcp setup
```

The wizard will:
- Auto-detect your XML export and PDF directory
- Create the configuration
- Index your library
- Configure Claude Desktop automatically

### 4. Restart Claude Desktop

Quit and reopen Claude Desktop. You'll see "EndNote Library" in your MCP connectors.

That's it. Start asking Claude about your references.

## Commands

| Command | What It Does |
|---------|-------------|
| `endnote-mcp setup` | Interactive setup wizard |
| `endnote-mcp index` | Re-index after adding new references (incremental) |
| `endnote-mcp index --full` | Full re-index from scratch |
| `endnote-mcp index --skip-pdfs` | Index metadata only (fast, ~1 sec) |
| `endnote-mcp status` | Show index statistics |
| `endnote-mcp install` | Add to Claude Desktop config |
| `endnote-mcp serve` | Start MCP server (used by Claude Desktop automatically) |

## Tools Available to Claude

| Tool | Description |
|------|-------------|
| `search_references` | Search by author, title, year, keywords, abstract (BM25 ranked) |
| `search_fulltext` | Search inside PDF content — find concepts, quotes, methods |
| `get_reference_details` | Full metadata for a reference (abstract, keywords, DOI, etc.) |
| `get_citation` | Format as APA 7th, Harvard, Vancouver, Chicago, or IEEE |
| `read_pdf_section` | Read specific pages from a PDF attachment |
| `list_references_by_topic` | Broad topic-based listing |
| `rebuild_index` | Re-index after updating your EndNote library |

## Adding New References

When you add new references to your EndNote library:

1. **Re-export XML** from EndNote (overwrite the same file)
2. Either:
   - Run `endnote-mcp index` from a terminal, **or**
   - Ask Claude: *"Rebuild my library index"*

Indexing is **incremental** — it only processes new references and PDFs, not the entire library again.

## Performance

| Operation | Time (4,000 references) |
|-----------|------------------------|
| Metadata indexing | ~1 second |
| PDF extraction (first time) | ~1 min per 100 PDFs |
| PDF extraction (incremental) | Only new PDFs |
| Search queries | < 50 ms |

## Configuration

Config is stored at:
- **macOS**: `~/Library/Application Support/endnote-mcp/config.yaml`
- **Windows**: `%APPDATA%/endnote-mcp/config.yaml`
- **Linux**: `~/.config/endnote-mcp/config.yaml`

```yaml
endnote_xml: /path/to/your/library.xml
pdf_dir: /path/to/your/Library.Data/PDF
db_path: /path/to/library.db    # auto-set by setup
max_pdf_pages: 30                # max pages per read request
```

## Citation Styles

Five built-in styles:

- **APA 7th** — `get_citation(rec_number=42, style="apa7")`
- **Harvard** — `style="harvard"`
- **Vancouver** — `style="vancouver"`
- **Chicago** (Author-Date, 17th ed.) — `style="chicago"`
- **IEEE** — `style="ieee"`

## Troubleshooting

**"No configuration found"** — Run `endnote-mcp setup`

**"XML file not found"** — Re-export from EndNote: File → Export → XML format

**"PDF not found"** — Check that `pdf_dir` in your config points to the correct `.Data/PDF` directory

**Search returns no results** — Run `endnote-mcp index` to rebuild the database

**Claude Desktop doesn't show the tool** — Run `endnote-mcp install`, then restart Claude Desktop

## Citing This Software

If you use this tool in your research, please cite it:

> Gokmen, G. (2026). *EndNote MCP: Connecting EndNote Reference Libraries to Claude AI* (Version 1.0.0) [Computer software]. https://doi.org/10.5281/zenodo.18617547

Or use the "Cite this repository" button on GitHub for BibTeX/APA formats.

## License

AGPL-3.0 — free to use, modify, and distribute. See [LICENSE](LICENSE) for details.
