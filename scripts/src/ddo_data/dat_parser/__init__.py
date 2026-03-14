"""Turbine .dat archive parser for DDO/LOTRO game files."""

from .archive import DatArchive, DatHeader, FileEntry
from .btree import BTreeNode, read_btree_node, traverse_btree
from .compare import compare_entries_by_type, CompareResult, FieldAnalysis
from .decompress import decompress_entry
from .extract import scan_file_table, read_entry_data, extract_entry
from .survey import survey_entries, SurveyResult, TypeGroup
from .tagged import (
    scan_tagged_entry,
    scan_tlv,
    scan_all_hypotheses,
    validate_file_refs,
    parse_entry_header,
    TLVResult,
    Property,
    EntryHeader,
)

__all__ = [
    "DatArchive",
    "DatHeader",
    "FileEntry",
    "BTreeNode",
    "read_btree_node",
    "traverse_btree",
    "CompareResult",
    "FieldAnalysis",
    "compare_entries_by_type",
    "decompress_entry",
    "scan_file_table",
    "read_entry_data",
    "extract_entry",
    "SurveyResult",
    "TypeGroup",
    "survey_entries",
    "scan_tagged_entry",
    "scan_tlv",
    "scan_all_hypotheses",
    "validate_file_refs",
    "parse_entry_header",
    "TLVResult",
    "Property",
    "EntryHeader",
]
