"""Tests for litscout.utils.identifiers."""

from litscout.utils.identifiers import (
    extract_doi_from_string,
    normalize_doi,
    reconstruct_abstract,
    sanitize_for_filename,
)


def test_normalize_doi_basic():
    assert normalize_doi("10.1038/s41586-023-06424-7") == "10.1038/s41586-023-06424-7"


def test_normalize_doi_url():
    assert normalize_doi("https://doi.org/10.1038/S41586-023-06424-7") == "10.1038/s41586-023-06424-7"


def test_normalize_doi_dx():
    assert normalize_doi("http://dx.doi.org/10.1038/S41586") == "10.1038/s41586"


def test_normalize_doi_none():
    assert normalize_doi(None) is None
    assert normalize_doi("") is None


def test_sanitize_for_filename():
    assert sanitize_for_filename("10.1038/s41586-023-06424-7") == "10.1038_s41586-023-06424-7"
    assert sanitize_for_filename("s2:abc123") == "s2abc123"


def test_sanitize_for_filename_special_chars():
    assert sanitize_for_filename('test<>:"|file') == "testfile"


def test_reconstruct_abstract():
    inverted_index = {
        "This": [0],
        "is": [1],
        "a": [2],
        "test": [3],
        "abstract": [4],
    }
    assert reconstruct_abstract(inverted_index) == "This is a test abstract"


def test_reconstruct_abstract_empty():
    assert reconstruct_abstract({}) == ""


def test_reconstruct_abstract_with_duplicates():
    inverted_index = {
        "the": [0, 4],
        "cat": [1],
        "sat": [2],
        "on": [3],
        "mat": [5],
    }
    result = reconstruct_abstract(inverted_index)
    assert result == "the cat sat on the mat"


def test_extract_doi_from_string():
    assert extract_doi_from_string("10.1038_s41586-023-06424-7.pdf") == "10.1038/s41586-023-06424-7"


def test_extract_doi_from_complex_filename():
    result = extract_doi_from_string("nature_10.1038_s41586-023-06424-7_download.pdf")
    assert result is not None
    assert "10.1038" in result


def test_extract_doi_no_match():
    assert extract_doi_from_string("random_file.pdf") is None
