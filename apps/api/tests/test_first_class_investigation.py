"""Tests for adapter_result_run and first_class_investigation (no network)."""

from __future__ import annotations

import asyncio
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_API = Path(__file__).resolve().parents[1]
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from adapter_result_run import AdapterResult, run_adapter
from first_class_investigation import (
    _fetch_courtlistener,
    build_journalist_investigation_record,
    build_outlet_investigation_record,
)

# ---------------------------------------------------------------------------
# Fixtures — base kwargs
# ---------------------------------------------------------------------------

JOURNALIST_KWARGS = dict(
    display_name="Jane Doe",
    publication="The Tribune",
    article_url="https://example.com/article",
    article_topic="healthcare",
    article_text="Jane Doe reports on hospital funding.",
    named_entities=[{"text": "Jane Doe", "label": "PERSON"}],
    linked_article_analysis_id="aaa-111",
)

OUTLET_KWARGS = dict(
    outlet_display="The Tribune",
    domain="tribune.com",
    linked_article_analysis_id="aaa-222",
    article_url="https://tribune.com/article",
)


def _make_fec_rows(n: int = 2) -> list[dict]:
    return [{"contributor_name": f"Donor {i}", "contribution_receipt_amount": 500} for i in range(n)]


def _make_cl_rows(n: int = 2) -> list[dict]:
    return [
        {"case_name": f"Case {i}", "court": "SCOTUS", "date_filed": "2023-01-01", "url": f"https://cl.law/{i}"}
        for i in range(n)
    ]


def _make_member() -> dict:
    return {"member_id": "M001", "full_name": "Jane Doe", "party": "D", "state": "CA"}


def _make_votes(n: int = 3) -> list[dict]:
    return [{"vote_position": "Yes", "bill": f"HR{i}"} for i in range(n)]


def _make_bills() -> dict:
    return {"bills": [{"bill_id": "HR1", "title": "Health Act"}]}


def _make_sec() -> dict:
    return {"entities": [{"name": "Doe Media LLC", "cik": "0001234567"}]}


def _make_lda() -> dict:
    return {"filingCount": 2, "filings": [{}, {}]}


def _gdelt_echo_stub() -> dict:
    return {
        "total_articles": 0,
        "unique_domains": 0,
        "unique_countries": 0,
        "echo_score": 0.0,
        "top_domains": [],
    }


@pytest.fixture(autouse=True)
def _mock_gdelt_adapter():
    """Avoid real GDELT HTTP when building journalist investigations."""
    with (
        patch("adapters.gdelt.search_byline_corpus", AsyncMock(return_value=[])),
        patch("adapters.gdelt.get_narrative_echo_score", AsyncMock(return_value=_gdelt_echo_stub())),
    ):
        yield


def _all_adapter_patches(
    *,
    fec=None,
    member=None,
    votes=None,
    bills=None,
    sec=None,
    lda=None,
):
    return {
        "first_class_investigation._fetch_fec_schedule_a_individual": fec if fec is not None else _make_fec_rows(),
        "first_class_investigation.search_member_by_name": member if member is not None else _make_member(),
        "first_class_investigation.fetch_congress_bills": bills if bills is not None else _make_bills(),
        "first_class_investigation.sec_edgar.search_entity": sec if sec is not None else _make_sec(),
        "first_class_investigation.fetch_lda_by_name": lda if lda is not None else _make_lda(),
        "first_class_investigation.get_recent_votes": votes if votes is not None else _make_votes(),
        "first_class_investigation._quoted_sources_payload": [],
    }


def _patch_courtlistener(rows):
    """Patch CourtListener as loaded from `adapters.courtlistener` inside _fetch_courtlistener."""
    mock_cl = MagicMock()
    mock_cl.search_opinions = AsyncMock(return_value=rows)
    return patch.dict("sys.modules", {"adapters.courtlistener": mock_cl})


def _patch_journalist(patches: dict):
    stack = ExitStack()
    for target, value in patches.items():
        if asyncio.iscoroutine(value) or callable(value):
            stack.enter_context(patch(target, side_effect=value))
        else:
            stack.enter_context(patch(target, return_value=value))
    return stack


# ---------------------------------------------------------------------------
# Unit: AdapterResult
# ---------------------------------------------------------------------------


class TestAdapterResult:
    def test_ok_record_shape(self):
        r = AdapterResult(adapter="fec", ok=True, value=[1, 2], rows_returned=2, latency_ms=42.5)
        rec = r.to_source_record()
        assert rec["adapter"] == "fec"
        assert rec["ok"] is True
        assert rec["latency_ms"] == 42.5
        assert rec["rows_returned"] == 2
        assert "timed_out" not in rec

    def test_timeout_record_shape(self):
        r = AdapterResult(
            adapter="lda",
            ok=False,
            timed_out=True,
            source_error=True,
            detail="timeout_after_8.0s",
            latency_ms=8001.0,
        )
        rec = r.to_source_record()
        assert rec["ok"] is False
        assert rec["timed_out"] is True
        assert rec["source_error"] is True
        assert "timeout" in rec["detail"]

    def test_detail_truncated_at_500(self):
        r = AdapterResult(adapter="x", ok=False, detail="x" * 600)
        rec = r.to_source_record()
        assert len(rec["detail"]) == 500

    def test_latency_always_present(self):
        r = AdapterResult(adapter="x", ok=True)
        rec = r.to_source_record()
        assert "latency_ms" in rec
        assert rec["latency_ms"] >= 0

    def test_error_type_in_record(self):
        err = ValueError("boom")
        r = AdapterResult(adapter="x", ok=False, error=err, source_error=True, detail="boom", latency_ms=5.0)
        row = r.to_source_record()
        assert row["error_type"] == "ValueError"


# ---------------------------------------------------------------------------
# Unit: run_adapter
# ---------------------------------------------------------------------------


class TestRunAdapter:
    @pytest.mark.asyncio
    async def test_success_sync(self):
        result = await run_adapter(lambda: 42, adapter="test", timeout=30.0)
        assert result.ok is True
        assert result.value == 42
        assert result.latency_ms >= 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_success_async(self):
        async def _coro():
            return {"key": "val"}

        result = await run_adapter(_coro, adapter="test", timeout=30.0)
        assert result.ok is True
        assert result.value == {"key": "val"}

    @pytest.mark.asyncio
    async def test_exception_captured(self):
        def _boom():
            raise ValueError("downstream exploded")

        result = await run_adapter(_boom, adapter="test", timeout=30.0)
        assert result.ok is False
        assert result.source_error is True
        assert isinstance(result.error, ValueError)
        assert "downstream exploded" in (result.detail or "")

    @pytest.mark.asyncio
    async def test_timeout(self):
        async def _slow():
            await asyncio.sleep(10)

        result = await run_adapter(_slow, adapter="test", timeout=0.05)
        assert result.ok is False
        assert result.timed_out is True
        assert result.source_error is True
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        async def _cancellable():
            await asyncio.sleep(10)

        task = asyncio.create_task(run_adapter(_cancellable, adapter="test", timeout=60.0))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_latency_nonzero_on_slow_call(self):
        async def _slight_delay():
            await asyncio.sleep(0.05)
            return True

        result = await run_adapter(_slight_delay, adapter="test", timeout=30.0)
        assert result.latency_ms >= 40


# ---------------------------------------------------------------------------
# Unit: _fetch_courtlistener
# ---------------------------------------------------------------------------


class TestFetchCourtlistener:
    @pytest.mark.asyncio
    async def test_empty_name_returns_empty(self):
        result = await _fetch_courtlistener("")
        assert result.ok is True
        assert result.value == []

    @pytest.mark.asyncio
    async def test_short_name_returns_empty(self):
        result = await _fetch_courtlistener("x")
        assert result.ok is True
        assert result.value == []

    @pytest.mark.asyncio
    async def test_happy_path_slims_rows(self):
        rows = _make_cl_rows(3)
        with _patch_courtlistener(rows):
            result = await _fetch_courtlistener("Jane Doe")
        assert result.ok is True
        assert len(result.value) == 3
        assert all("case_name" in r for r in result.value)
        assert result.rows_returned == 3

    @pytest.mark.asyncio
    async def test_skips_non_dict_rows(self):
        rows = [{"case_name": "Good Case", "court": "X", "date_filed": "2023-01-01", "url": "u"}, "bad", None]
        with _patch_courtlistener(rows):
            result = await _fetch_courtlistener("Jane Doe")
        assert result.ok is True
        assert len(result.value) == 1

    @pytest.mark.asyncio
    async def test_adapter_error_returns_failed_result(self):
        mock_cl = MagicMock()
        mock_cl.search_opinions = AsyncMock(side_effect=RuntimeError("CL down"))
        with patch.dict("sys.modules", {"adapters.courtlistener": mock_cl}):
            result = await _fetch_courtlistener("Jane Doe")
        assert result.ok is False
        assert result.source_error is True


# ---------------------------------------------------------------------------
# Integration: build_journalist_investigation_record
# ---------------------------------------------------------------------------


class TestJournalistInvestigation:
    @pytest.mark.asyncio
    async def test_all_adapters_succeed(self):
        patches = _all_adapter_patches()
        cl_rows = _make_cl_rows(2)

        with _patch_courtlistener(cl_rows), _patch_journalist(patches):
            result = await build_journalist_investigation_record(**JOURNALIST_KWARGS)

        assert result["receipt_type"] == "journalist_investigation"
        assert result["fec_donations"] is not None
        assert len(result["fec_donations"]) == 2
        assert result["courtlistener_opinions"] is not None
        assert result["congress_member"] is not None
        assert result["congress_votes"] is not None
        assert result["congress_bills"] is not None
        assert result["sec_edgar"] is not None
        assert result["lda_filings"] is not None

        assert all(s["ok"] for s in result["data_sources"])
        assert all("latency_ms" in s for s in result["data_sources"])

        im = result["investigation_meta"]
        assert set(im["adapters"].keys()) == {
            "fec_schedule_a",
            "courtlistener",
            "propublica_congress_member",
            "propublica_congress_votes",
            "congress_gov",
            "sec_edgar",
            "lda",
        }
        for row in im["adapters"].values():
            assert set(row.keys()) == {"status", "latency_ms", "error_type"}

        lb = result["layer_b"]
        assert lb is not None
        assert "prior_coverage" in lb and "source_audits" in lb

    @pytest.mark.asyncio
    async def test_no_byline_skips_all_adapters(self):
        kwargs = {**JOURNALIST_KWARGS, "display_name": ""}
        with patch("first_class_investigation._quoted_sources_payload", return_value=[]):
            result = await build_journalist_investigation_record(**kwargs)

        assert result["fec_donations"] is None
        assert result["courtlistener_opinions"] is None
        assert len(result["data_sources"]) == 1
        assert result["data_sources"][0]["detail"] == "no_byline"
        assert result["investigation_meta"]["adapters"]["journalist_subject"]["status"] == "error"
        assert result.get("layer_b") is None

    @pytest.mark.asyncio
    async def test_one_adapter_times_out(self):
        def _fec_slow(*_a, **_kw):
            time.sleep(10)

        with (
            _patch_courtlistener(_make_cl_rows(1)),
            patch("first_class_investigation._fetch_fec_schedule_a_individual", side_effect=_fec_slow),
            patch("first_class_investigation.search_member_by_name", return_value=_make_member()),
            patch("first_class_investigation.fetch_congress_bills", return_value=_make_bills()),
            patch("first_class_investigation.sec_edgar.search_entity", return_value=_make_sec()),
            patch("first_class_investigation.fetch_lda_by_name", return_value=_make_lda()),
            patch("first_class_investigation.get_recent_votes", return_value=_make_votes()),
            patch("first_class_investigation._quoted_sources_payload", return_value=[]),
        ):
            result = await build_journalist_investigation_record(**JOURNALIST_KWARGS)

        sources = {s["adapter"]: s for s in result["data_sources"]}
        assert sources["fec_schedule_a"]["ok"] is False
        assert sources["fec_schedule_a"].get("timed_out") is True
        assert result["fec_donations"] is None
        assert result["courtlistener_opinions"] is not None
        assert result["congress_member"] is not None

    @pytest.mark.asyncio
    async def test_one_adapter_throws(self):
        with (
            _patch_courtlistener(_make_cl_rows(1)),
            patch("first_class_investigation._fetch_fec_schedule_a_individual", return_value=_make_fec_rows()),
            patch("first_class_investigation.search_member_by_name", return_value=_make_member()),
            patch("first_class_investigation.fetch_congress_bills", return_value=_make_bills()),
            patch("first_class_investigation.sec_edgar.search_entity", side_effect=RuntimeError("EDGAR down")),
            patch("first_class_investigation.fetch_lda_by_name", return_value=_make_lda()),
            patch("first_class_investigation.get_recent_votes", return_value=_make_votes()),
            patch("first_class_investigation._quoted_sources_payload", return_value=[]),
        ):
            result = await build_journalist_investigation_record(**JOURNALIST_KWARGS)

        assert result["sec_edgar"] is None
        sources = {s["adapter"]: s for s in result["data_sources"]}
        assert sources["sec_edgar"]["ok"] is False
        assert "EDGAR down" in (sources["sec_edgar"].get("detail") or "")
        assert result["fec_donations"] is not None

    @pytest.mark.asyncio
    async def test_malformed_fec_response(self):
        with (
            _patch_courtlistener([]),
            patch("first_class_investigation._fetch_fec_schedule_a_individual", return_value="not-a-list"),
            patch("first_class_investigation.search_member_by_name", return_value=None),
            patch("first_class_investigation.fetch_congress_bills", return_value={}),
            patch("first_class_investigation.sec_edgar.search_entity", return_value={}),
            patch("first_class_investigation.fetch_lda_by_name", return_value={}),
            patch("first_class_investigation._quoted_sources_payload", return_value=[]),
        ):
            result = await build_journalist_investigation_record(**JOURNALIST_KWARGS)

        assert result["fec_donations"] is None
        sources = {s["adapter"]: s for s in result["data_sources"]}
        assert sources["fec_schedule_a"]["ok"] is False

    @pytest.mark.asyncio
    async def test_no_congress_member_skips_votes(self):
        votes_mock = MagicMock()
        with (
            _patch_courtlistener([]),
            patch("first_class_investigation._fetch_fec_schedule_a_individual", return_value=[]),
            patch("first_class_investigation.search_member_by_name", return_value=None),
            patch("first_class_investigation.fetch_congress_bills", return_value={}),
            patch("first_class_investigation.sec_edgar.search_entity", return_value={}),
            patch("first_class_investigation.fetch_lda_by_name", return_value={}),
            patch("first_class_investigation.get_recent_votes", votes_mock),
            patch("first_class_investigation._quoted_sources_payload", return_value=[]),
        ):
            result = await build_journalist_investigation_record(**JOURNALIST_KWARGS)

        votes_mock.assert_not_called()
        assert result["congress_votes"] is None
        assert result["congress_member"] is None
        sources = {s["adapter"]: s for s in result["data_sources"]}
        assert sources["propublica_congress_member"]["detail"] == "no_member_match"

    @pytest.mark.asyncio
    async def test_missing_congress_api_key(self):
        with (
            _patch_courtlistener([]),
            patch("first_class_investigation._fetch_fec_schedule_a_individual", return_value=[]),
            patch("first_class_investigation.search_member_by_name", return_value=None),
            patch("first_class_investigation.fetch_congress_bills", return_value={"error": "missing_api_key"}),
            patch("first_class_investigation.sec_edgar.search_entity", return_value={}),
            patch("first_class_investigation.fetch_lda_by_name", return_value={}),
            patch("first_class_investigation._quoted_sources_payload", return_value=[]),
        ):
            result = await build_journalist_investigation_record(**JOURNALIST_KWARGS)

        sources = {s["adapter"]: s for s in result["data_sources"]}
        assert sources["congress_gov"]["ok"] is False
        assert "CONGRESS_API_KEY" in (sources["congress_gov"].get("detail") or "")

    @pytest.mark.asyncio
    async def test_all_adapters_fail(self):
        mock_cl = MagicMock()
        mock_cl.search_opinions = AsyncMock(side_effect=RuntimeError("CL down"))
        with (
            patch.dict("sys.modules", {"adapters.courtlistener": mock_cl}),
            patch("first_class_investigation._fetch_fec_schedule_a_individual", side_effect=RuntimeError),
            patch("first_class_investigation.search_member_by_name", side_effect=RuntimeError),
            patch("first_class_investigation.fetch_congress_bills", side_effect=RuntimeError),
            patch("first_class_investigation.sec_edgar.search_entity", side_effect=RuntimeError),
            patch("first_class_investigation.fetch_lda_by_name", side_effect=RuntimeError),
            patch("first_class_investigation._quoted_sources_payload", return_value=[]),
        ):
            result = await build_journalist_investigation_record(**JOURNALIST_KWARGS)

        assert result["receipt_type"] == "journalist_investigation"
        assert result["fec_donations"] is None
        assert result["sec_edgar"] is None
        assert result["lda_filings"] is None
        assert all(not s["ok"] for s in result["data_sources"])

    @pytest.mark.asyncio
    async def test_data_sources_audit_trail_complete(self):
        with (
            _patch_courtlistener(_make_cl_rows(1)),
            patch("first_class_investigation._fetch_fec_schedule_a_individual", return_value=_make_fec_rows()),
            patch("first_class_investigation.search_member_by_name", return_value=_make_member()),
            patch("first_class_investigation.fetch_congress_bills", return_value=_make_bills()),
            patch("first_class_investigation.sec_edgar.search_entity", return_value=_make_sec()),
            patch("first_class_investigation.fetch_lda_by_name", return_value=_make_lda()),
            patch("first_class_investigation.get_recent_votes", return_value=_make_votes()),
            patch("first_class_investigation._quoted_sources_payload", return_value=[]),
        ):
            result = await build_journalist_investigation_record(**JOURNALIST_KWARGS)

        adapter_names = [s["adapter"] for s in result["data_sources"]]
        expected = {
            "fec_schedule_a",
            "courtlistener",
            "propublica_congress_member",
            "propublica_congress_votes",
            "congress_gov",
            "sec_edgar",
            "lda",
        }
        assert set(adapter_names) == expected
        assert len(adapter_names) == len(set(adapter_names))

    @pytest.mark.asyncio
    async def test_report_id_is_unique_across_calls(self):
        with (
            _patch_courtlistener([]),
            patch("first_class_investigation._fetch_fec_schedule_a_individual", return_value=[]),
            patch("first_class_investigation.search_member_by_name", return_value=None),
            patch("first_class_investigation.fetch_congress_bills", return_value={}),
            patch("first_class_investigation.sec_edgar.search_entity", return_value={}),
            patch("first_class_investigation.fetch_lda_by_name", return_value={}),
            patch("first_class_investigation._quoted_sources_payload", return_value=[]),
        ):
            r1 = await build_journalist_investigation_record(**JOURNALIST_KWARGS)
            r2 = await build_journalist_investigation_record(**JOURNALIST_KWARGS)

        assert r1["report_id"] != r2["report_id"]


# ---------------------------------------------------------------------------
# Integration: build_outlet_investigation_record
# ---------------------------------------------------------------------------


class TestOutletInvestigation:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        mock_pub = {"name": "The Tribune"}
        with (
            patch("publisher_registry.lookup_domain", return_value=mock_pub),
            patch("publisher_registry.parent_company_for_domain", return_value="Tribune Co"),
            _patch_courtlistener(_make_cl_rows(2)),
            patch("first_class_investigation.sec_edgar.search_entity", return_value=_make_sec()),
            patch("first_class_investigation.fetch_fec_by_name", return_value={"candidates": []}),
            patch("first_class_investigation.fetch_lda_by_name", return_value=_make_lda()),
            patch("first_class_investigation.fetch_irs990_by_name", return_value={"filings": []}),
        ):
            result = await build_outlet_investigation_record(**OUTLET_KWARGS)

        assert result["receipt_type"] == "outlet_investigation"
        assert result["subject"]["parent_company"] == "Tribune Co"
        assert result["subject"]["registry_match"] is True
        assert result["courtlistener_opinions"] is not None
        assert result["sec_edgar"] is not None
        assert result["irs990"] is not None
        assert all("latency_ms" in s for s in result["data_sources"])
        assert set(result["investigation_meta"]["adapters"].keys()) == {
            "courtlistener",
            "sec_edgar",
            "fec",
            "lda",
            "irs990",
        }
        assert result["layer_b"] is not None
        assert "outlet_ownership" in result["layer_b"]

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        with (
            patch("publisher_registry.lookup_domain", return_value={}),
            patch("publisher_registry.parent_company_for_domain", return_value=None),
            _patch_courtlistener(_make_cl_rows(1)),
            patch("first_class_investigation.sec_edgar.search_entity", return_value=_make_sec()),
            patch("first_class_investigation.fetch_fec_by_name", return_value={}),
            patch("first_class_investigation.fetch_lda_by_name", side_effect=RuntimeError("LDA down")),
            patch("first_class_investigation.fetch_irs990_by_name", side_effect=RuntimeError("IRS down")),
        ):
            result = await build_outlet_investigation_record(**OUTLET_KWARGS)

        assert result["lda_filings"] is None
        assert result["irs990"] is None
        assert result["courtlistener_opinions"] is not None
        assert result["sec_edgar"] is not None

        sources = {s["adapter"]: s for s in result["data_sources"]}
        assert sources["lda"]["ok"] is False
        assert sources["irs990"]["ok"] is False
        assert sources["courtlistener"]["ok"] is True

    @pytest.mark.asyncio
    async def test_unknown_domain(self):
        with (
            patch("publisher_registry.lookup_domain", return_value={}),
            patch("publisher_registry.parent_company_for_domain", return_value=None),
            _patch_courtlistener([]),
            patch("first_class_investigation.sec_edgar.search_entity", return_value={}),
            patch("first_class_investigation.fetch_fec_by_name", return_value={}),
            patch("first_class_investigation.fetch_lda_by_name", return_value={}),
            patch("first_class_investigation.fetch_irs990_by_name", return_value={}),
        ):
            result = await build_outlet_investigation_record(**OUTLET_KWARGS)

        assert result["subject"]["registry_match"] is False
        assert result["subject"]["outlet"] == "The Tribune"
