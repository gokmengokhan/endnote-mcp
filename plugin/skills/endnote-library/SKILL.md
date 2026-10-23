---
name: endnote-library
description: Find, cite and quote sources from the user's EndNote library via endnote-mcp. Use for references, citations, bibliographies, BibTeX, quotes with page numbers, or checking a draft's citations.
compatibility: Needs the endnote-mcp server (https://github.com/gokmengokhan/endnote-mcp) connected as an MCP server, with the user's library indexed.
---

# EndNote library

The endnote-mcp server indexes the user's EndNote library, exported from EndNote as XML, together with the text of the attached PDFs. Search results show each record as `[n]`; every other tool takes that record number.

## Rules

- **Cite only records the tools return.** Format them with `get_citation`, `get_bibliography` or `get_bibtex`; never write a reference from memory. If the library has nothing suitable, say so, and mark anything you add from general knowledge as not from the library.
- **Quote only text you have read** with `search_fulltext` or `read_pdf_section`, word for word. Search matches word stems, so a hit does not prove the exact wording: read the page before quoting.
- **Page numbers in tool output count PDF pages from 1**, not the numbers printed on them. PDF page 2 of an article printed as pp. 244–253 is p. 245. For a citation, read the page and use its printed number; if none is visible, write "PDF p. 2" and say so.
- **Absent from the library is not the same as nonexistent.** Report it as a gap the user can fill in EndNote.
- **Citations reproduce the EndNote record as entered.** If a record looks wrong (no year, garbled authors), compare it with the PDF's first page and tell the user; don't silently correct it.
- **One paper can have two record numbers** (duplicate records). Use one, and mention the duplicate when it matters, for example in a bibliography.

## Which search tool

| Need | Tool |
| --- | --- |
| Most questions; start here | `search_library`: metadata, PDF text and (if installed) semantic search in one call; records found by several methods rank first |
| Known author, title words or year | `search_references`, with the `author`, `year_from` and `year_to` filters |
| Exact wording or a passage inside the PDFs | `search_fulltext` with a "quoted phrase" |
| A concept the papers may word differently | `search_semantic`; if it reports that it is unavailable, use `search_library` |
| What the library holds on a theme | `list_references_by_topic` |
| More like a given record | `find_related` |

Terms match literally, so punctuation is safe; "quoted phrases", `AND`, `OR`, `NOT` and a trailing `*` work. Queries ignore accents but the `author` filter does not, so if `author` finds nothing, put the surname in the query instead. Keep `limit` at 5–10 for `search_fulltext` and `search_library`: their PDF snippets are long.

## Workflows

**Find and cite sources.** Search, then confirm the work with `get_reference_details` (abstract, DOI, whether its PDF is indexed). Format with `get_citation` for one record, `get_bibliography` for several (`sort` by `author` or `year`), or `get_bibtex` for LaTeX. Styles: `apa7`, `harvard`, `vancouver`, `chicago`, `ieee`.

**Check a quotation.** Search a distinctive 4–8 word fragment as a "quoted phrase" with `search_fulltext`. If nothing comes back, try a shorter fragment: PDF line breaks and hyphenation split words. Read the matching page with `read_pdf_section` and compare word for word. Report exact, differs (show both versions) or not found, with the printed page number.

**Verify a draft's references.** For each in-text citation:

1. Find the record with `search_references`: surname in the query, year filters a year either side of the cited year (online-first and print years often differ).
2. Classify it: in the library, not found, or mismatched (year, spelling, title).
3. Where the sentence makes a specific claim, check it in the PDF with `search_fulltext`, then `read_pdf_section`: supported, not supported, or no PDF to check.
4. Report one row per citation: citation, record `[n]`, status, evidence page, suggested fix.

Go through every citation; don't stop at the first problem.

**Read a paper.** `read_pdf_section` returns 5 pages by default and up to 30 per call. Find the relevant pages with `search_fulltext` first rather than reading the whole file. "Indexed PDF pages: 0" in `get_reference_details` means the attachment has no searchable text, usually because it is a scan: it can be cited, but not searched or quoted until the user OCRs it and re-indexes.

## When something seems missing

New references appear only after the user re-exports the library from EndNote (File > Export, XML format, overwriting the same file) and the index is rebuilt, with `rebuild_index` or `endnote-mcp index` in a terminal. Indexing is incremental, so repeat runs are quick. You can't do the export yourself, so ask the user to do it first.
