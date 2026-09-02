"""Read-only Tool 1 opportunity grid for the capability-statement app."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import OrderedDict
from datetime import date, datetime, timezone
from urllib.request import Request, urlopen

import streamlit as st

from scraper_trigger import ScraperTriggerError, dispatch_scraper, get_trigger_token


SHEET_ID = "1vXqBDRHiHdyf8U4O_ZuIR5nOLQa-jgEphjuRCoctx14"
SHEET_TAB = "Opportunities"
SHEET_CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq"
    f"?tqx=out:csv&sheet={SHEET_TAB}"
)

REQUIRED_HEADERS = (
    "portal_source",
    "opportunity_title",
    "funder_organisation",
    "country_region",
    "deadline",
    "contract_value",
    "opportunity_link",
    "summary",
    "relevance_score",
    "bid_recommendation",
    "risk_flags",
    "review_status",
    "scraped_at",
    "matched_keywords",
)


class OpportunitySchemaError(ValueError):
    """Raised when Tool 1's Sheet does not satisfy schema v1.1."""


def _normalise_header(value: str) -> str:
    return (value or "").strip().casefold()


def validate_headers(headers: list[str]) -> dict[str, int]:
    """Validate schema v1.1 and return canonical header positions."""
    positions: dict[str, int] = {}
    duplicates: list[str] = []
    for index, value in enumerate(headers):
        normalised = _normalise_header(value)
        if not normalised:
            continue
        if normalised in positions:
            duplicates.append(value)
        else:
            positions[normalised] = index

    if duplicates:
        raise OpportunitySchemaError(
            "Schema incompatible — duplicate columns: "
            + ", ".join(str(value) for value in duplicates)
        )

    missing = [name for name in REQUIRED_HEADERS if name not in positions]
    if missing:
        raise OpportunitySchemaError(
            "Schema incompatible — missing columns: " + ", ".join(missing)
        )
    return {name: positions[name] for name in REQUIRED_HEADERS}


def parse_matched_keywords(value: str) -> list[str]:
    """Parse Tool 1's authoritative JSON keyword list defensively."""
    if not value or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def parse_scraped_at(value: str) -> datetime | None:
    """Return a timezone-aware discovery timestamp, or None when invalid."""
    if not value or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _parse_deadline(value: str) -> date | None:
    if not value or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _parse_score(value: str) -> float | None:
    if not value or not value.strip():
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def format_relevance(value: str) -> str:
    """Display a relevance value accurately.

    Fresh scraper records may carry qualitative labels (low/medium/high) or
    numeric scores. Show qualitative labels verbatim (title-cased), numeric
    values compactly, and degrade blank/malformed values to "Unavailable"
    without crashing.
    """
    if value is None:
        return "Unavailable"
    text = str(value).strip()
    if not text:
        return "Unavailable"
    numeric = _parse_score(text)
    if numeric is not None:
        return f"{numeric:g}"
    return text[:1].upper() + text[1:]


def deduplicate_keywords(keywords) -> list[str]:
    """Deduplicate keywords case-insensitively, preserving the first readable
    spelling (and accented characters). Blank/malformed items are dropped.
    """
    if not keywords:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in keywords:
        if item is None:
            continue
        text = str(item).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result

SELECTED_OPPORTUNITY_KEY = "selected_opportunity"


def select_opportunity(session_state, opportunity) -> None:
    """Store the chosen opportunity in Streamlit session state.

    Selecting an opportunity records it for capability-statement preparation.
    It intentionally does not touch the ToR-upload state.
    """
    session_state[SELECTED_OPPORTUNITY_KEY] = opportunity


def clear_selected_opportunity(session_state) -> None:
    """Clear the selected opportunity, leaving unrelated state untouched."""
    session_state[SELECTED_OPPORTUNITY_KEY] = None


def get_selected_opportunity(session_state):
    """Return the currently selected opportunity, or None."""
    return session_state.get(SELECTED_OPPORTUNITY_KEY)


def parse_opportunities_csv(csv_text: str) -> list[dict]:
    """Parse a header-name-driven Sheet export into defensive row records."""
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise OpportunitySchemaError("Schema incompatible — Sheet is empty")
    positions = validate_headers(rows[0])

    opportunities: list[dict] = []
    for sheet_order, row in enumerate(rows[1:]):
        if not any((cell or "").strip() for cell in row):
            continue

        def value(name: str) -> str:
            index = positions[name]
            return row[index].strip() if index < len(row) else ""

        opportunity = {name: value(name) for name in REQUIRED_HEADERS}
        opportunity["matched_keywords_list"] = parse_matched_keywords(
            opportunity["matched_keywords"]
        )
        opportunity["scraped_at_datetime"] = parse_scraped_at(
            opportunity["scraped_at"]
        )
        opportunity["deadline_date"] = _parse_deadline(opportunity["deadline"])
        opportunity["relevance_score_number"] = _parse_score(
            opportunity["relevance_score"]
        )
        opportunity["_sheet_order"] = sheet_order
        opportunities.append(opportunity)
    return opportunities


@st.cache_data(ttl=120, show_spinner=False)
def _download_csv_text(csv_url: str) -> str:
    request = Request(csv_url, headers={"User-Agent": "GovRisk-Captool/1.0"})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8-sig")


def fetch_opportunities(csv_url: str = SHEET_CSV_URL) -> list[dict]:
    """Fetch and parse the live read-only Sheet export."""
    return parse_opportunities_csv(_download_csv_text(csv_url))


def filter_opportunities(
    opportunities: list[dict],
    portal_sources: list[str] | None = None,
    recommendations: list[str] | None = None,
) -> list[dict]:
    """Apply optional exact-value filters without assuming valid cells."""
    sources = set(portal_sources or [])
    decisions = set(recommendations or [])
    return [
        opportunity
        for opportunity in opportunities
        if (not sources or opportunity.get("portal_source") in sources)
        and (
            not decisions
            or opportunity.get("bid_recommendation") in decisions
        )
    ]


def deduplicate_opportunities(opportunities: list[dict]) -> list[dict]:
    """Return one display record per stable opportunity link.

    Historical Sheets may contain duplicate links from runs that predate
    cross-run deduplication. Prefer the richer/newer row so schema v1.1
    metadata is not hidden by an older legacy row.
    """
    selected: dict[str, dict] = {}
    unkeyed: list[dict] = []

    def richness(item: dict) -> tuple[int, int, int]:
        return (
            item.get("scraped_at_datetime") is not None,
            bool(item.get("matched_keywords_list")),
            item.get("_sheet_order", 0),
        )

    for opportunity in opportunities:
        link = (opportunity.get("opportunity_link") or "").strip()
        if not link:
            unkeyed.append(opportunity)
            continue
        existing = selected.get(link)
        if existing is None or richness(opportunity) > richness(existing):
            selected[link] = opportunity

    return sorted(
        [*selected.values(), *unkeyed],
        key=lambda item: item.get("_sheet_order", 0),
    )


def discovery_week_label(opportunity: dict) -> str:
    """Group only by discovery time; deadline is never a freshness proxy."""
    scraped_at = opportunity.get("scraped_at_datetime")
    if scraped_at is None:
        return "Discovery date unavailable"
    week_start = scraped_at.date()
    week_start = week_start.fromordinal(week_start.toordinal() - week_start.weekday())
    return f"Week of {week_start.strftime('%d %b %Y')}"


def group_opportunities(opportunities: list[dict]) -> OrderedDict[str, list[dict]]:
    """Group newest discovery weeks first and sort each group by deadline."""
    def group_sort_key(item: dict):
        timestamp = item.get("scraped_at_datetime")
        return timestamp.timestamp() if timestamp else float("-inf")

    def row_sort_key(item: dict):
        deadline = item.get("deadline_date")
        return (
            deadline is None,
            deadline or date.max,
            item.get("_sheet_order", 0),
        )

    grouped: OrderedDict[str, list[dict]] = OrderedDict()
    for opportunity in sorted(opportunities, key=group_sort_key, reverse=True):
        label = discovery_week_label(opportunity)
        grouped.setdefault(label, []).append(opportunity)
    for items in grouped.values():
        items.sort(key=row_sort_key)
    return grouped


def _record_key(opportunity: dict) -> str:
    identity = opportunity.get("opportunity_link") or str(
        opportunity.get("_sheet_order", "")
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]


def _render_card(opportunity: dict) -> None:
    with st.container(border=True):
        source = opportunity.get("portal_source") or "Unknown source"
        st.caption(source.upper())
        st.write(opportunity.get("opportunity_title") or "Untitled opportunity")

        funder = opportunity.get("funder_organisation") or "Funder unavailable"
        geography = opportunity.get("country_region") or "Geography unavailable"
        st.caption(f"{funder} · {geography}")

        deadline = opportunity.get("deadline") or "Unavailable"
        recommendation = opportunity.get("bid_recommendation") or "Not assessed"
        score_text = format_relevance(opportunity.get("relevance_score"))
        st.caption(
            f"Deadline: {deadline} · Relevance: {score_text} · {recommendation}"
        )

        keywords = deduplicate_keywords(opportunity.get("matched_keywords_list"))
        st.caption("Why it matched")
        if keywords:
            st.write(" · ".join(keywords))
        else:
            st.caption("Matched keywords unavailable for this historical record")

        link = opportunity.get("opportunity_link")
        action_columns = st.columns(2)
        with action_columns[0]:
            if link:
                st.link_button("Open opportunity ↗", link, use_container_width=True)
        with action_columns[1]:
            if st.button(
                "Select for capability statement",
                key=f"select_opportunity_{_record_key(opportunity)}",
                use_container_width=True,
            ):
                select_opportunity(st.session_state, opportunity)
                st.rerun()


def render_opportunity_panel() -> dict | None:
    """Render the live grid and return the selected opportunity, if any."""
    st.subheader("Opportunity Monitor")
    st.caption(
        "Live, read-only results from Tool 1. Discovery week comes from "
        "scraped_at; deadline is shown separately."
    )

    trigger_token = get_trigger_token()
    if trigger_token:
        trigger_col, refresh_col, status_col = st.columns([1.4, 1, 2])
        with trigger_col:
            if st.button(
                "Run opportunity scan",
                type="primary",
                use_container_width=True,
            ):
                try:
                    dispatch_scraper(trigger_token)
                    st.session_state["scan_requested"] = True
                    st.success(
                        "Scan started. Results will appear here when Tool 1 finishes."
                    )
                except ScraperTriggerError as exc:
                    st.error(str(exc))
    else:
        refresh_col, status_col = st.columns([1, 3])
    with refresh_col:
        if st.button("Refresh results", use_container_width=True):
            _download_csv_text.clear()
            st.rerun()

    try:
        opportunities = deduplicate_opportunities(fetch_opportunities())
    except OpportunitySchemaError as exc:
        st.error(str(exc))
        return get_selected_opportunity(st.session_state)
    except Exception:
        st.error(
            "Opportunity results are temporarily unavailable. "
            "The capability-statement workflow remains available."
        )
        return get_selected_opportunity(st.session_state)

    with status_col:
        st.metric("Opportunities available", len(opportunities))

    if trigger_token and st.session_state.get("scan_requested"):
        st.info("Tool 1 is running. Refresh results in a few minutes.")

    aggregate_keywords = [
        keyword
        for opportunity in opportunities
        for keyword in opportunity.get("matched_keywords_list", [])
    ]
    matched_terms = sorted(
        deduplicate_keywords(aggregate_keywords),
        key=str.casefold,
    )
    if matched_terms:
        st.caption("Keywords that matched the displayed results")
        st.write(" · ".join(matched_terms))

    source_options = sorted(
        {item["portal_source"] for item in opportunities if item["portal_source"]}
    )
    recommendation_options = sorted(
        {
            item["bid_recommendation"]
            for item in opportunities
            if item["bid_recommendation"]
        }
    )
    filter_columns = st.columns(2)
    with filter_columns[0]:
        selected_sources = st.multiselect("Source", source_options)
    with filter_columns[1]:
        selected_recommendations = st.multiselect(
            "Recommendation", recommendation_options
        )

    visible = filter_opportunities(
        opportunities,
        selected_sources,
        selected_recommendations,
    )
    if not visible:
        st.info("No opportunities match the selected filters.")
    else:
        for label, group in group_opportunities(visible).items():
            st.markdown(f"#### {label}")
            for index in range(0, len(group), 2):
                card_columns = st.columns(2)
                for column, opportunity in zip(card_columns, group[index:index + 2]):
                    with column:
                        _render_card(opportunity)

    selected = get_selected_opportunity(st.session_state)
    if selected:
        title = selected.get("opportunity_title") or "Untitled opportunity"
        st.success(
            f"Opportunity selected: {title}. Open the opportunity, download the "
            "ToR, then upload it below to begin."
        )
        if st.button("Change or clear selection", key="clear_selected_opportunity"):
            clear_selected_opportunity(st.session_state)
            st.rerun()
    return selected
