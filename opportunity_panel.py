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


# ---------------------------------------------------------------------------
# Browser v2 pure helpers: search, sort, pagination, table rows, metadata.
# These are pure functions so behaviour is unit-testable without Streamlit.
# None of them mutate the input records.
# ---------------------------------------------------------------------------

# View modes.
VIEW_TABLE = "Table"
VIEW_CARDS = "Detailed cards"
VIEW_OPTIONS = (VIEW_TABLE, VIEW_CARDS)

# Sort options (labels are the exact UI copy).
SORT_NEWEST = "Newest discovered"
SORT_DEADLINE = "Deadline soonest"
SORT_RELEVANCE = "Highest relevance"
SORT_SHEET = "Sheet order"
SORT_OPTIONS = (SORT_NEWEST, SORT_DEADLINE, SORT_RELEVANCE, SORT_SHEET)

# Rows-per-page options and default.
PAGE_SIZE_OPTIONS = (10, 20, 50)
DEFAULT_PAGE_SIZE = 10

# Qualitative relevance ranking (higher is better).
_QUALITATIVE_RELEVANCE = {"high": 3, "medium": 2, "low": 1}

NO_RESULTS_MESSAGE = "No opportunities match your search and filters."

# Ordered, user-facing table columns (no internal fields are ever included).
TABLE_COLUMNS = (
    "Source",
    "Opportunity",
    "Funder",
    "Geography",
    "Discovery week",
    "Deadline",
    "Relevance",
    "Recommendation",
    "Matched keywords",
    "Open",
)


def opportunity_identity(opportunity: dict) -> str:
    """Return the stable identity for a record: its opportunity_link.

    Never the visible row number. Falls back to the sheet order only when a link
    is genuinely absent, so preview/selection matching stays stable across
    sorting and pagination.
    """
    link = (opportunity.get("opportunity_link") or "").strip()
    if link:
        return link
    return "sheet-order:{}".format(opportunity.get("_sheet_order", ""))


def _searchable_text(opportunity: dict) -> str:
    """Concatenate the searchable fields of a record into one casefolded string.

    Casefold handles case-insensitivity and preserves accented characters as
    readable text (it does not strip diacritics).
    """
    parts = [
        opportunity.get("opportunity_title") or "",
        opportunity.get("funder_organisation") or "",
        opportunity.get("country_region") or "",
        opportunity.get("summary") or "",
    ]
    parts.extend(str(k) for k in opportunity.get("matched_keywords_list") or [])
    return "  ".join(parts).casefold()


def search_opportunities(opportunities: list[dict], query: str) -> list[dict]:
    """Case-insensitively search title, funder, geography, summary, keywords.

    Whitespace-only (or empty) query means no filtering. Records are not mutated
    and original order is preserved.
    """
    if not query or not query.strip():
        return list(opportunities)
    needle = query.strip().casefold()
    return [o for o in opportunities if needle in _searchable_text(o)]


def _relevance_rank(opportunity: dict):
    """Return a sortable relevance rank; higher is more relevant.

    Numeric scores rank by value; qualitative High/Medium/Low map to 3/2/1.
    Unavailable/malformed values return None so callers can order them last.
    """
    numeric = opportunity.get("relevance_score_number")
    if numeric is not None:
        return float(numeric)
    raw = opportunity.get("relevance_score")
    if isinstance(raw, str):
        rank = _QUALITATIVE_RELEVANCE.get(raw.strip().casefold())
        if rank is not None:
            return float(rank)
    return None


def sort_opportunities(opportunities: list[dict], sort_mode: str) -> list[dict]:
    """Return a new, deterministically-sorted list (input not mutated).

    Stable tie-breaker is always the authoritative sheet order. Records whose
    sort value is unavailable/malformed are placed last.
    """
    items = list(opportunities)

    def sheet_order(o: dict) -> int:
        value = o.get("_sheet_order", 0)
        return value if isinstance(value, int) else 0

    if sort_mode == SORT_NEWEST:
        def key(o):
            ts = o.get("scraped_at_datetime")
            available = ts is not None
            # Newest first: available before unavailable; within available,
            # larger timestamp first. Sheet order breaks ties ascending.
            return (
                0 if available else 1,
                -ts.timestamp() if available else 0.0,
                sheet_order(o),
            )
        return sorted(items, key=key)

    if sort_mode == SORT_DEADLINE:
        def key(o):
            d = o.get("deadline_date")
            available = d is not None
            return (
                0 if available else 1,
                d.toordinal() if available else 0,
                sheet_order(o),
            )
        return sorted(items, key=key)

    if sort_mode == SORT_RELEVANCE:
        def key(o):
            rank = _relevance_rank(o)
            available = rank is not None
            return (
                0 if available else 1,
                -rank if available else 0.0,
                sheet_order(o),
            )
        return sorted(items, key=key)

    # SORT_SHEET (and any unknown value) -> authoritative sheet order.
    return sorted(items, key=sheet_order)


def clamp_page(page: int, total_items: int, page_size: int) -> int:
    """Clamp a 1-based page into the valid range for the current result size."""
    total_pages = page_count(total_items, page_size)
    if not isinstance(page, int) or page < 1:
        return 1
    if page > total_pages:
        return total_pages
    return page


def page_count(total_items: int, page_size: int) -> int:
    """Return the number of pages (at least 1, even when there are no items)."""
    if page_size <= 0:
        return 1
    if total_items <= 0:
        return 1
    return (total_items + page_size - 1) // page_size


def paginate(opportunities: list[dict], page: int, page_size: int) -> list[dict]:
    """Return only the records on the clamped current page."""
    safe_page = clamp_page(page, len(opportunities), page_size)
    start = (safe_page - 1) * page_size
    return opportunities[start:start + page_size]


def page_bounds(total_items: int, page: int, page_size: int) -> tuple[int, int]:
    """Return 1-based (start, end) item numbers for the current page.

    For an empty result set returns (0, 0) so callers can show a no-results
    state instead of a misleading "Showing 1-0".
    """
    if total_items <= 0:
        return (0, 0)
    safe_page = clamp_page(page, total_items, page_size)
    start = (safe_page - 1) * page_size + 1
    end = min(safe_page * page_size, total_items)
    return (start, end)


def keywords_in_results(opportunities: list[dict]) -> list[str]:
    """Aggregate matched keywords across the given (filtered) result set.

    De-duplicated case-insensitively (preserving readable accented spelling) and
    sorted case-insensitively. Callers pass the FULL filtered set, not the
    current page and not the unfiltered records.
    """
    aggregate = [
        keyword
        for opportunity in opportunities
        for keyword in opportunity.get("matched_keywords_list") or []
    ]
    return sorted(deduplicate_keywords(aggregate), key=str.casefold)


def latest_scraped_at(opportunities: list[dict]) -> datetime | None:
    """Return the latest valid timezone-aware scraped_at, or None if none exist."""
    timestamps = [
        o.get("scraped_at_datetime")
        for o in opportunities
        if o.get("scraped_at_datetime") is not None
    ]
    return max(timestamps) if timestamps else None


def format_results_updated(opportunities: list[dict]) -> str:
    """Return the 'Results last updated' line with an explicit fallback."""
    latest = latest_scraped_at(opportunities)
    if latest is None:
        return "Results last updated: unavailable"
    return "Results last updated: {}".format(
        latest.strftime("%Y-%m-%d %H:%M UTC")
    )


def build_table_row(opportunity: dict) -> dict:
    """Build one safe, display-only table row from a record.

    Only user-facing fields are included — never _sheet_order, parsed datetimes,
    or record hashes. Missing values degrade to clear labels or blanks. Includes
    a hidden-from-config 'identity' value keyed on opportunity_link so callers can
    map a selected row back to its record without trusting the row number.
    """
    keywords = deduplicate_keywords(opportunity.get("matched_keywords_list"))
    return {
        "Source": (opportunity.get("portal_source") or "").strip() or "Unknown source",
        "Opportunity": (opportunity.get("opportunity_title") or "").strip()
        or "Untitled opportunity",
        "Funder": (opportunity.get("funder_organisation") or "").strip()
        or "Funder unavailable",
        "Geography": (opportunity.get("country_region") or "").strip()
        or "Geography unavailable",
        "Discovery week": discovery_week_label(opportunity),
        "Deadline": (opportunity.get("deadline") or "").strip() or "Unavailable",
        "Relevance": format_relevance(opportunity.get("relevance_score")),
        "Recommendation": (opportunity.get("bid_recommendation") or "").strip()
        or "Not assessed",
        "Matched keywords": " · ".join(keywords) if keywords else "",
        "Open": (opportunity.get("opportunity_link") or "").strip() or None,
    }


def build_table_rows(opportunities: list[dict]) -> list[dict]:
    """Build display rows for the given (already paginated) records."""
    return [build_table_row(o) for o in opportunities]


def find_by_identity(opportunities: list[dict], identity: str) -> dict | None:
    """Return the record whose stable identity matches, or None."""
    if not identity:
        return None
    for opportunity in opportunities:
        if opportunity_identity(opportunity) == identity:
            return opportunity
    return None


def table_instance_key(signature: tuple, page: int, page_size, page_records) -> str:
    """Return a deterministic Streamlit widget key for the current table instance.

    Streamlit keeps ``st.dataframe`` selection state keyed by widget key. A
    CONSTANT key would let a positional row selection survive when the underlying
    records change (pagination, search, filter, sort, or page-size changes),
    previewing/selecting the wrong record. By folding the query signature, page,
    page size, and the ordered visible ``opportunity_link`` identities into the
    key, any change to the visible page yields a NEW widget key — so the new page
    renders with no stale selection.

    Pure and deterministic: identical state + identical records give the same
    key; any change gives a different key.
    """
    identities = tuple(opportunity_identity(o) for o in (page_records or []))
    material = repr((signature, page, page_size, identities))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return "opp_browser_table_{}".format(digest)


# Namespaced session-state keys for the browser (avoid clashing with app keys).
NS = "opp_browser_"
KEY_VIEW = NS + "view"
KEY_SEARCH = NS + "search"
KEY_SOURCES = NS + "sources"
KEY_RECOMMENDATIONS = NS + "recommendations"
KEY_SORT = NS + "sort"
KEY_PAGE_SIZE = NS + "page_size"
KEY_PAGE = NS + "page"
KEY_PREVIEW = NS + "preview_identity"
KEY_QUERY_SIGNATURE = NS + "query_signature"


def query_signature(
    search: str, sources, recommendations, sort_mode: str, page_size=None
) -> tuple:
    """A hashable signature of the inputs that must reset pagination to page 1.

    ``page_size`` participates so that changing Rows per page resets pagination
    to page 1 (the visible window changes, so a stale later page is meaningless).
    It is optional for backwards compatibility with existing callers/tests.
    """
    return (
        (search or "").strip().casefold(),
        tuple(sorted(sources or [])),
        tuple(sorted(recommendations or [])),
        sort_mode or "",
        page_size,
    )


def resolve_current_page(session_state, signature: tuple) -> int:
    """Return the page to use, resetting to 1 when the query signature changed.

    Pure w.r.t. the passed mapping: it reads and updates ``session_state`` but
    contains no Streamlit calls, so it is unit-testable with a plain dict.
    """
    previous = session_state.get(KEY_QUERY_SIGNATURE)
    if previous != signature:
        session_state[KEY_QUERY_SIGNATURE] = signature
        session_state[KEY_PAGE] = 1
        return 1
    return session_state.get(KEY_PAGE, 1)


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


def _render_preview(opportunity: dict) -> None:
    """Preview a single opportunity below the table.

    Previewing does NOT select the capability-statement opportunity. Only the
    explicit button in this preview updates session state.
    """
    with st.container(border=True):
        title = opportunity.get("opportunity_title") or "Untitled opportunity"
        st.markdown(f"**{title}**")

        source = (opportunity.get("portal_source") or "Unknown source").strip()
        funder = opportunity.get("funder_organisation") or "Funder unavailable"
        geography = opportunity.get("country_region") or "Geography unavailable"
        deadline = opportunity.get("deadline") or "Unavailable"
        recommendation = opportunity.get("bid_recommendation") or "Not assessed"
        score_text = format_relevance(opportunity.get("relevance_score"))

        st.write(f"Source: {source.upper()}")
        st.write(f"Funder: {funder}")
        st.write(f"Geography: {geography}")
        st.write(f"Deadline: {deadline}")
        st.write(f"Relevance: {score_text}")
        st.write(f"Recommendation: {recommendation}")

        keywords = deduplicate_keywords(opportunity.get("matched_keywords_list"))
        if keywords:
            st.write("Matched keywords: " + " · ".join(keywords))
        else:
            st.caption("Matched keywords unavailable for this historical record")

        summary = (opportunity.get("summary") or "").strip()
        if summary:
            st.write(summary)

        link = opportunity.get("opportunity_link")
        if link:
            st.link_button("Open opportunity ↗", link)

        if st.button(
            "Select for capability statement",
            key=f"preview_select_{_record_key(opportunity)}",
        ):
            select_opportunity(st.session_state, opportunity)
            st.rerun()


def render_opportunity_panel() -> dict | None:
    """Render the searchable, paginated browser and return the selection."""
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

    # --- Controls: view, search, filters, sort, page size ------------------
    view_mode = st.radio(
        "View",
        VIEW_OPTIONS,
        horizontal=True,
        key=KEY_VIEW,
    )

    search = st.text_input("Search opportunities", key=KEY_SEARCH)

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
    filter_columns = st.columns([2, 2, 2, 1])
    with filter_columns[0]:
        selected_sources = st.multiselect("Source", source_options, key=KEY_SOURCES)
    with filter_columns[1]:
        selected_recommendations = st.multiselect(
            "Recommendation", recommendation_options, key=KEY_RECOMMENDATIONS
        )
    with filter_columns[2]:
        sort_mode = st.selectbox("Sort results", SORT_OPTIONS, key=KEY_SORT)
    with filter_columns[3]:
        page_size = st.selectbox(
            "Rows per page", PAGE_SIZE_OPTIONS, key=KEY_PAGE_SIZE
        )

    # --- Pipeline: search -> filter -> sort (before pagination) ------------
    searched = search_opportunities(opportunities, search)
    filtered = filter_opportunities(
        searched, selected_sources, selected_recommendations
    )
    ordered = sort_opportunities(filtered, sort_mode)

    total_available = len(opportunities)
    total_filtered = len(ordered)

    # --- Results metadata --------------------------------------------------
    meta_cols = st.columns(2)
    with meta_cols[0]:
        st.caption(f"{total_available} opportunities available")
    with meta_cols[1]:
        st.caption(f"{total_filtered} matching your search and filters")
    st.caption(format_results_updated(opportunities))

    matched_terms = keywords_in_results(ordered)
    if matched_terms:
        st.caption("Keywords in filtered results")
        st.write(" · ".join(matched_terms))

    # --- Pagination page resolution (reset to 1 on query change) -----------
    signature = query_signature(
        search, selected_sources, selected_recommendations, sort_mode, page_size
    )
    current_page = resolve_current_page(st.session_state, signature)
    current_page = clamp_page(current_page, total_filtered, page_size)
    st.session_state[KEY_PAGE] = current_page

    if total_filtered == 0:
        st.info(NO_RESULTS_MESSAGE)
        return _render_selection_footer()

    total_pages = page_count(total_filtered, page_size)
    start, end = page_bounds(total_filtered, current_page, page_size)
    page_records = paginate(ordered, current_page, page_size)

    st.caption(
        f"Showing {start}–{end} of {total_filtered} opportunities"
    )

    if view_mode == VIEW_CARDS:
        # Cards receive ONLY the current page, not every result.
        for index in range(0, len(page_records), 2):
            card_columns = st.columns(2)
            for column, opportunity in zip(
                card_columns, page_records[index:index + 2]
            ):
                with column:
                    _render_card(opportunity)
    else:
        # A deterministic, content-derived key ensures a changed page starts
        # without a stale positional selection carried over by Streamlit.
        instance_key = table_instance_key(
            signature, current_page, page_size, page_records
        )
        _render_table(page_records, instance_key)

    # --- Pagination controls ----------------------------------------------
    prev_col, label_col, next_col = st.columns([1, 2, 1])
    with prev_col:
        if st.button(
            "Previous", disabled=current_page <= 1, use_container_width=True
        ):
            st.session_state[KEY_PAGE] = max(1, current_page - 1)
            st.rerun()
    with label_col:
        st.caption(f"Page {current_page} of {total_pages}")
    with next_col:
        if st.button(
            "Next",
            disabled=current_page >= total_pages,
            use_container_width=True,
        ):
            st.session_state[KEY_PAGE] = min(total_pages, current_page + 1)
            st.rerun()

    return _render_selection_footer()


def _render_table(page_records: list[dict], instance_key: str) -> None:
    """Render the compact read-only table with native single-row selection.

    ``instance_key`` must uniquely identify the current visible page/query so a
    stale positional selection from a previous table instance cannot leak into a
    changed page.
    """
    import pandas as pd

    rows = build_table_rows(page_records)
    frame = pd.DataFrame(rows, columns=TABLE_COLUMNS)

    event = st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Source": st.column_config.TextColumn("Source", width="small"),
            "Opportunity": st.column_config.TextColumn("Opportunity", width="large"),
            "Funder": st.column_config.TextColumn("Funder", width="medium"),
            "Geography": st.column_config.TextColumn("Geography", width="small"),
            "Discovery week": st.column_config.TextColumn(
                "Discovery week", width="small"
            ),
            "Deadline": st.column_config.TextColumn("Deadline", width="small"),
            "Relevance": st.column_config.TextColumn("Relevance", width="small"),
            "Recommendation": st.column_config.TextColumn(
                "Recommendation", width="small"
            ),
            "Matched keywords": st.column_config.TextColumn(
                "Matched keywords", width="medium"
            ),
            "Open": st.column_config.LinkColumn(
                "Open", display_text="Open ↗", width="small"
            ),
        },
        key=instance_key,
    )

    # Map the selected visible row back to its record by stable identity.
    selected_rows = []
    try:
        selected_rows = event.selection["rows"]  # type: ignore[attr-defined]
    except Exception:
        selected_rows = []

    if selected_rows:
        row_index = selected_rows[0]
        if 0 <= row_index < len(page_records):
            previewed = page_records[row_index]
            st.session_state[KEY_PREVIEW] = opportunity_identity(previewed)
            st.markdown("#### Preview")
            _render_preview(previewed)


def _render_selection_footer() -> dict | None:
    """Render the persistent selected-opportunity footer and return selection."""
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
