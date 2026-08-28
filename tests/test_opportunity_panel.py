"""Contract tests for the read-only Tool 1 opportunity grid."""

import csv
import io
import json

import pytest

from opportunity_panel import (
    REQUIRED_HEADERS,
    OpportunitySchemaError,
    deduplicate_opportunities,
    discovery_week_label,
    filter_opportunities,
    group_opportunities,
    parse_matched_keywords,
    parse_opportunities_csv,
    parse_scraped_at,
    validate_headers,
)


def _csv(headers=None, rows=None):
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers or REQUIRED_HEADERS)
    for row in rows or []:
        writer.writerow(row)
    return output.getvalue()


def _row(**overrides):
    values = {header: "" for header in REQUIRED_HEADERS}
    values.update(
        {
            "portal_source": "undp",
            "opportunity_title": "Justice sector reform",
            "opportunity_link": "https://example.test/opportunity/1",
            "deadline": "2026-09-30",
            "scraped_at": "2026-08-27T12:30:00Z",
            "matched_keywords": json.dumps(
                ["anticorrupción", "asset recovery"], ensure_ascii=False
            ),
        }
    )
    values.update(overrides)
    return [values[header] for header in REQUIRED_HEADERS]


def test_schema_accepts_required_headers_in_any_order():
    headers = list(reversed(REQUIRED_HEADERS))
    positions = validate_headers(headers)
    assert positions["matched_keywords"] == 0
    assert positions["portal_source"] == len(headers) - 1


def test_schema_ignores_unknown_additional_columns():
    positions = validate_headers(["mark_notes", *REQUIRED_HEADERS])
    assert positions["portal_source"] == 1


def test_schema_rejects_missing_required_headers():
    headers = [header for header in REQUIRED_HEADERS if header != "scraped_at"]
    with pytest.raises(OpportunitySchemaError, match="scraped_at"):
        validate_headers(headers)


def test_schema_rejects_case_and_whitespace_duplicate():
    with pytest.raises(OpportunitySchemaError, match="duplicate"):
        validate_headers([*REQUIRED_HEADERS, " PORTAL_SOURCE "])


def test_parser_preserves_authoritative_accented_keywords():
    result = parse_opportunities_csv(_csv(rows=[_row()]))
    assert result[0]["matched_keywords_list"] == [
        "anticorrupción",
        "asset recovery",
    ]


@pytest.mark.parametrize("value", ["", "not-json", "{}", '"keyword"'])
def test_malformed_or_legacy_keyword_cells_degrade_to_empty(value):
    assert parse_matched_keywords(value) == []


def test_naive_or_invalid_discovery_timestamp_is_unavailable():
    assert parse_scraped_at("2026-08-27T12:30:00") is None
    assert parse_scraped_at("not-a-date") is None


def test_week_grouping_uses_scraped_at_not_deadline():
    csv_text = _csv(
        rows=[
            _row(
                scraped_at="",
                deadline="2099-01-01",
                opportunity_link="https://example.test/legacy",
            )
        ]
    )
    opportunity = parse_opportunities_csv(csv_text)[0]
    assert discovery_week_label(opportunity) == "Discovery date unavailable"


def test_groups_newest_discovery_week_first_and_unavailable_last():
    csv_text = _csv(
        rows=[
            _row(
                scraped_at="",
                opportunity_link="https://example.test/legacy",
            ),
            _row(
                scraped_at="2026-08-17T09:00:00Z",
                opportunity_link="https://example.test/old",
            ),
            _row(
                scraped_at="2026-08-27T09:00:00Z",
                opportunity_link="https://example.test/new",
            ),
        ]
    )
    labels = list(group_opportunities(parse_opportunities_csv(csv_text)))
    assert labels == [
        "Week of 24 Aug 2026",
        "Week of 17 Aug 2026",
        "Discovery date unavailable",
    ]


def test_filters_source_and_recommendation_together():
    opportunities = [
        {"portal_source": "undp", "bid_recommendation": "BID"},
        {"portal_source": "usaid", "bid_recommendation": "BID"},
        {"portal_source": "undp", "bid_recommendation": "NO BID"},
    ]
    assert filter_opportunities(opportunities, ["undp"], ["BID"]) == [
        opportunities[0]
    ]


def test_parser_keeps_opportunity_link_as_identity_field():
    result = parse_opportunities_csv(_csv(rows=[_row()]))
    assert result[0]["opportunity_link"] == "https://example.test/opportunity/1"


def test_duplicate_links_collapse_to_richer_schema_v11_record():
    csv_text = _csv(
        rows=[
            _row(
                scraped_at="",
                matched_keywords="",
                opportunity_title="Legacy row",
            ),
            _row(
                scraped_at="2026-08-27T12:30:00Z",
                matched_keywords='["justice reform"]',
                opportunity_title="Enriched row",
            ),
        ]
    )
    result = deduplicate_opportunities(parse_opportunities_csv(csv_text))
    assert len(result) == 1
    assert result[0]["opportunity_title"] == "Enriched row"
    assert result[0]["matched_keywords_list"] == ["justice reform"]
