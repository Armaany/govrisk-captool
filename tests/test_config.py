"""Smoke tests for config.py — Task 1.5"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import config

def test_model_name():
    assert config.MODEL_NAME == "claude-sonnet-4-5"

def test_max_tokens_per_chunk():
    assert config.MAX_TOKENS_PER_CHUNK == 500

def test_chunk_overlap_tokens():
    assert config.CHUNK_OVERLAP_TOKENS == 50

def test_max_retrieval_results():
    assert config.MAX_RETRIEVAL_RESULTS == 20

def test_geography_options_count():
    assert len(config.GEOGRAPHY_OPTIONS) == 9

def test_geography_options_contents():
    expected = [
        "Mexico", "Colombia", "Peru", "Brazil",
        "Caribbean", "Central America", "Argentina",
        "Chile", "Regional / LATAM"
    ]
    assert config.GEOGRAPHY_OPTIONS == expected

def test_thematic_options_count():
    assert len(config.THEMATIC_OPTIONS) == 10

def test_thematic_options_contents():
    expected = [
        "AML/CFT", "CTF/Terrorist Financing", "Anti-corruption",
        "FIU Strengthening", "Asset Recovery", "Justice Reform",
        "Beneficial Ownership", "DNFBP Supervision",
        "Illicit Financial Flows", "Human Trafficking"
    ]
    assert config.THEMATIC_OPTIONS == expected

def test_funder_options_count():
    assert len(config.FUNDER_OPTIONS) == 6

def test_funder_options_contents():
    expected = ["US State Dept", "UK FCDO", "IDB", "USAID", "IADB", "Other"]
    assert config.FUNDER_OPTIONS == expected

def test_paths_defined():
    assert config.CAPABILITY_LIBRARY_PATH == "./capability_library/"
    assert config.CHROMA_DB_PATH == "./chroma_db/"
    assert config.OUTPUT_PATH == "./output/"
