"""Extract tests. Synthetic files only; the model is replaced by a fake backend."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from epicrisis.classify.backend import BackendError, UsageLimitReached
from epicrisis.classify.pages import page_refs
from epicrisis.classify.report import latest_pages
from epicrisis.cli import app
from epicrisis.consent import record_consent
from epicrisis.extract import backend as extract_backend
from epicrisis.extract.backend import PROMPT_VERSION, Extraction, build_request
from epicrisis.extract.run import call_chunks, document_refs, extract_source, load_extracted, sample_documents, write_document
from epicrisis.index.build import index_path
from epicrisis.inventory.run import write_inventory
from epicrisis.records import read_records
from epicrisis.sources import SourceRegistry, source_output_dir
from epicrisis.web.app import create_app
from test_inventory import SYNTHETIC_TEXT, make_scan_pdf, make_text_pdf

PRIVATE_NAME = "Clinic Ivanova oncology"


class FakeExtractBackend:
    name = "fake"
    model = "fake-sonnet"
    MOST_TOKENS = 1024  # the real one says how long an answer may be; so does this

    def __init__(self, fail_from: int | None = None, limit_from: int | None = None, model: str | None = None,
                 **rest):  # a backend is handed the call its engine makes; this one carries its own
        if model:
            self.model = model
        self.calls = []
        self.fail_from = fail_from
        self.limit_from = limit_from

    def extract(self, payloads, workdir: Path) -> Extraction:
        if self.limit_from is not None and len(self.calls) >= self.limit_from:
            raise UsageLimitReached("usage limit reached")
        self.calls.append(
            {
                "texts": [payload.text for payload in payloads],
                "images": [payload.image_path.name if payload.image_path else None for payload in payloads],
                "images_exist": all(payload.image_path.exists() for payload in payloads if payload.image_path),
                "workdir": workdir,
            }
        )
        if self.fail_from is not None and len(self.calls) > self.fail_from:
            raise BackendError("model call failed")
        count = len(payloads)
        return Extraction(
            fields={
                "title_as_printed": "Synthetic <b>panel</b>",
                "date_of_study_as_printed": "12.03.2003",
                "date_of_report_as_printed": None,
                "provider_as_printed": "Synthetic Lab",
                "department_as_printed": None,
                "language": "uk",
                "observations": [
                    {
                        "name_as_printed": f"Analyte {number}", "value_as_printed": "6,8", "value_numeric": 6.8,
                        "comparator": None, "value_kind": "quantitative", "unit_as_printed": "g/L",
                        "reference_as_printed": "4,0-9,0", "flag_as_printed": None, "method_as_printed": None,
                        "page": number, "snippet": f"Analyte {number} 6,8",
                    }  # fmt: skip
                    for number in range(1, count + 1)
                ],
                "sections": [{"heading_as_printed": "Conclusion", "text": "Synthetic conclusion", "page": count}],
                "page_texts": [{"page": number, "text": f"text of call page {number}\nAnalyte {number} 6,8 g/L 4,0-9,0"} for number in range(1, count + 1)],
                "medications_as_printed": [],
                "diagnoses_as_printed": ["Synthetic diagnosis"],
                "unreadable": [],
            },
            model="fake-sonnet-2026",
        )


def classify_line(record: dict, page: int, role: str, doc_type: str) -> dict:
    return {
        "file_sha256": record["sha256"], "page": page, "route": "vision", "doc_type": doc_type,
        "page_role": role, "language": "uk", "date_on_page": None, "provider_on_page": None,
        "has_tabular_results": False, "legible": True, "confidence": 0.9,
    }  # fmt: skip


@pytest.fixture
def setup(tmp_path):
    data_dir, source, output, records = build_archive(tmp_path)
    return data_dir, source, output, records


def setup_archive(tmp_path):
    """One synthetic archive, inventoried and classified, for tests that only need that much."""
    data_dir, source, output, _records = build_archive(tmp_path)
    return data_dir, source, output


def build_archive(tmp_path):
    archive = tmp_path / PRIVATE_NAME
    (archive / "2003").mkdir(parents=True)
    (archive / "2019").mkdir()
    make_scan_pdf(archive / "2003" / "long_scan.pdf", pages=10)
    make_text_pdf(archive / "2019" / "labs.pdf", [SYNTHETIC_TEXT, SYNTHETIC_TEXT + " page two"])
    make_scan_pdf(archive / "2019" / "invoice.pdf")

    data_dir = tmp_path / "data"
    source = SourceRegistry(data_dir).add(str(archive))
    data_dir = data_dir.resolve()
    output = source_output_dir(data_dir, source.id)
    write_inventory(archive, output / "inventory.jsonl")
    records = {record["name"]: record for record in read_records(output / "inventory.jsonl")}
    lines = [classify_line(records["long_scan.pdf"], p, "first" if p == 1 else "continuation", "discharge") for p in range(1, 11)]
    lines += [classify_line(records["labs.pdf"], 1, "first", "lab_panel"), classify_line(records["labs.pdf"], 2, "continuation", "lab_panel")]
    lines += [classify_line(records["invoice.pdf"], 1, "first", "insurance")]
    (output / "classify.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    return data_dir, source, output, records


def inventory_by_sha(output: Path) -> dict[str, dict]:
    return {record["sha256"]: record for record in read_records(output / "inventory.jsonl") if "sha256" in record}


def test_documents_to_extract_skip_filtered_types(setup):
    _, _, output, records = setup
    documents = document_refs(inventory_by_sha(output), latest_pages(output / "classify.jsonl"))
    assert {(doc.file_sha256, doc.pages) for doc in documents} == {
        (records["long_scan.pdf"]["sha256"], tuple(range(1, 11))),
        (records["labs.pdf"]["sha256"], (1, 2)),
    }


def test_files_still_being_classified_are_left_out(setup):
    _, _, output, records = setup
    pages = [page for page in latest_pages(output / "classify.jsonl") if not (page["file_sha256"] == records["long_scan.pdf"]["sha256"] and page["page"] == 10)]
    documents = document_refs(inventory_by_sha(output), pages)
    assert [doc.file_sha256 for doc in documents] == [records["labs.pdf"]["sha256"]]


def test_long_documents_are_cut_with_first_page_repeated(setup):
    _, _, _, records = setup
    refs = page_refs(records["long_scan.pdf"])
    assert [[ref.page for ref in chunk] for chunk in call_chunks(refs)] == [[1, 2, 3, 4, 5, 6, 7, 8], [1, 9, 10]]
    assert [[ref.page for ref in chunk] for chunk in call_chunks(refs[:8])] == [list(range(1, 9))]


def test_extract_merges_calls_and_maps_pages(setup):
    data_dir, source, output, records = setup
    fake = FakeExtractBackend()

    stats = extract_source(data_dir, source, fake)

    assert (stats.total, stats.extracted, len(fake.calls)) == (2, 2, 3)
    scan_calls = [call for call in fake.calls if call["images"][0]]
    text_calls = [call for call in fake.calls if call["texts"][0]]
    assert [len(call["images"]) for call in scan_calls] == [8, 3]
    assert scan_calls[0]["images"][0] == f"{records['long_scan.pdf']['sha256'][:16]}-01.png"
    assert all(call["images_exist"] and not call["workdir"].exists() for call in fake.calls)
    assert "Synthetic hemoglobin" in text_calls[0]["texts"][0]
    assert all(PRIVATE_NAME not in (text or "") for call in fake.calls for text in call["texts"])

    document = load_extracted(output / "extracted", records["long_scan.pdf"]["sha256"])["documents"][0]
    assert document["pages"] == list(range(1, 11))
    assert [item["provenance"]["page"] for item in document["observations"]] == list(range(1, 11))
    assert [item["page"] for item in document["page_texts"]] == list(range(1, 11))
    assert [item["page"] for item in document["sections"]] == [8, 10]
    assert document["diagnoses_as_printed"] == ["Synthetic diagnosis"]
    assert document["doc_type"] == "discharge" and document["title_as_printed"] == "Synthetic <b>panel</b>"
    assert document["provenance"] | {"extracted_at": None} == {
        "backend": "fake", "model": "fake-sonnet-2026", "requested_model": "fake-sonnet",
        "prompt_version": PROMPT_VERSION, "extracted_at": None, "calls": 2,
    }  # fmt: skip


def test_resume_usage_limit_and_retry(setup):
    data_dir, source, _, _ = setup

    first = extract_source(data_dir, source, FakeExtractBackend(), limit=1)
    stopped = extract_source(data_dir, source, FakeExtractBackend(limit_from=0), workers=1)
    failed = extract_source(data_dir, source, FakeExtractBackend(fail_from=0), workers=1)
    finished = extract_source(data_dir, source, FakeExtractBackend())

    assert first.extracted == 1
    assert (stopped.stopped, stopped.extracted) == ("usage_limit", 0)
    assert (failed.failed, failed.already_done) == (1, 1)
    assert (finished.extracted, finished.already_done) == (1, 1)


class UnreadableBackend(FakeExtractBackend):
    """Reports unreadable parts per call: whole-page calls first, then close-up calls."""

    def __init__(self, whole_page: int, close_up: int, **kwargs):
        super().__init__(**kwargs)
        self.counts = {False: whole_page, True: close_up}
        self.close_ups = []

    def extract(self, payloads, workdir: Path) -> Extraction:
        self.close_ups.append([[path.name for path in payload.close_ups] for payload in payloads])
        zoomed = any(payload.close_ups for payload in payloads)
        if zoomed:
            assert all(path.exists() for payload in payloads for path in payload.close_ups)
        extraction = super().extract(payloads, workdir)
        extraction.fields["unreadable"] = [{"page": 1, "what": "value", "why": "small print"}] * self.counts[zoomed]
        return extraction


def scan_document(output: Path, records: dict) -> dict:
    return load_extracted(output / "extracted", records["long_scan.pdf"]["sha256"])["documents"][0]


def test_close_up_pass_keeps_the_result_with_fewer_unreadable_parts(setup):
    data_dir, source, output, records = setup
    backend = UnreadableBackend(whole_page=2, close_up=1)

    stats = extract_source(data_dir, source, backend)

    # 10 scan pages: close-ups go 3 pages per call with page 1 repeated, so 5 calls. The text
    # document has unreadable parts too but went as text, so it gets no close-ups.
    assert (stats.extracted, stats.close_up_passes, stats.close_up_better) == (2, 1, 1)
    close_up_calls = [call for call in backend.close_ups if any(call)]
    assert len(close_up_calls) == 5 and all(len(call) <= 3 for call in close_up_calls)
    sha = records["long_scan.pdf"]["sha256"][:16]
    assert close_up_calls[0][0] == [f"{sha}-01{part}.png" for part in "abcd"]
    document = scan_document(output, records)
    assert document["provenance"]["close_up_pass"] | {"at": None} == {
        "status": "kept", "unreadable_before": 2, "unreadable_after": 1, "at": None,
    }  # fmt: skip

    rerun = UnreadableBackend(whole_page=2, close_up=1)
    assert extract_source(data_dir, source, rerun).already_done == 2 and rerun.calls == []


def test_close_up_pass_that_is_not_better_keeps_the_first_result(setup):
    data_dir, source, output, records = setup
    extract_source(data_dir, source, UnreadableBackend(whole_page=1, close_up=1))

    document = scan_document(output, records)
    assert document["provenance"]["close_up_pass"]["status"] == "not_better"
    assert len(document["unreadable"]) == 1


def test_documents_done_earlier_get_the_close_up_pass_once(setup):
    data_dir, source, output, records = setup
    # Stops at the usage limit right after the whole-page calls of the scan.
    extract_source(data_dir, source, UnreadableBackend(whole_page=1, close_up=0, limit_from=2), years={2003}, workers=1)
    assert "close_up_pass" not in scan_document(output, records)["provenance"]

    later = UnreadableBackend(whole_page=1, close_up=0)
    stats = extract_source(data_dir, source, later)

    assert (stats.close_up_only, stats.close_up_passes, stats.extracted) == (1, 1, 1)
    assert scan_document(output, records)["unreadable"] == []


def test_document_is_extracted_again_after_its_pages_are_classified_again(setup):
    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    lines = list(read_records(output / "classify.jsonl"))
    labs = records["labs.pdf"]["sha256"]
    newer = [dict(line, provenance={"classified_at": "2999-01-01T00:00:00+00:00"}) for line in lines if line["file_sha256"] == labs]
    (output / "classify.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines + newer))

    again = FakeExtractBackend()
    stats = extract_source(data_dir, source, again)

    assert (stats.extracted, stats.already_done) == (1, 1)
    assert again.calls[0]["texts"][0]


def test_years_and_sample(setup):
    data_dir, source, output, _ = setup
    documents = document_refs(inventory_by_sha(output), latest_pages(output / "classify.jsonl"))

    assert len(sample_documents(documents)) == 2
    assert extract_source(data_dir, source, FakeExtractBackend(), years={2019}).total == 1


def test_rewriting_a_document_replaces_overlapping_ones(tmp_path):
    for pages in ([1, 2], [2, 3], [5]):
        write_document(tmp_path, "a" * 64, {"pages": pages})
    assert [doc["pages"] for doc in load_extracted(tmp_path, "a" * 64)["documents"]] == [[2, 3], [5]]


def test_request_numbers_pages_and_keeps_text_out_of_arguments(tmp_path):
    from epicrisis.classify.pages import Payload

    request = build_request([Payload(image_path=tmp_path / "abc-01.png"), Payload(text="Synthetic page text")])
    assert "Page 1: the image file abc-01.png" in request
    assert "<<<PAGE 2\nSynthetic page text\nPAGE 2>>>" in request

    close_up = Payload(image_path=tmp_path / "abc-01.png", close_ups=[tmp_path / f"abc-01{part}.png" for part in "ab"])
    assert "abc-01.png in the current directory, with close-ups of the same page in abc-01a.png, abc-01b.png:" in build_request([close_up])


def test_cli_extract_checks_and_prints_numbers_only(setup, monkeypatch):
    data_dir, _, _, _ = setup
    monkeypatch.setattr(extract_backend, "ClaudeCodeExtractBackend", FakeExtractBackend)
    runner = CliRunner()

    refused = runner.invoke(app, ["extract", "--data-dir", str(data_dir)])
    record_consent(data_dir, FakeExtractBackend.name)
    accepted = runner.invoke(app, ["extract", "--data-dir", str(data_dir)])

    assert refused.exit_code == 2 and "not confirmed" in refused.output
    assert accepted.exit_code == 0, accepted.output
    assert "This run: extracted 2" in accepted.output
    assert "Documents extracted: 2 of 2" in accepted.output and "Values extracted: 12" in accepted.output
    assert PRIVATE_NAME not in accepted.output and "Synthetic panel" not in accepted.output


def test_card_page_shows_transcription_and_originals(setup):
    data_dir, source, _, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    labs, invoice = records["labs.pdf"]["sha256"], records["invoice.pdf"]["sha256"]

    card = client.get(f"/documents/{source.id}/{labs}/1")
    pending = client.get(f"/documents/{source.id}/{invoice}/1")
    listing = client.get("/documents").text

    assert card.status_code == 200
    assert "Results as printed" in card.text and "Analyte 2" in card.text and "4,0-9,0" in card.text
    assert "Synthetic &lt;b&gt;panel&lt;/b&gt;" in card.text and "<b>panel" not in card.text
    assert "not yet checked by a person" in card.text
    assert f"/sources/{source.id}/files/{labs}/pages/2" in card.text
    assert "Synthetic diagnosis" in card.text and "text of call page 1" in card.text
    assert pending.status_code == 200 and "Not transcribed yet" in pending.text
    assert card.text.index("Results as printed") < card.text.index("Text by section")
    report = client.get(f"/documents/{source.id}/{records['long_scan.pdf']['sha256']}/1").text
    assert "Measurements as printed" in report and "Results as printed" not in report
    assert report.index("Text by section") < report.index("Measurements as printed")
    assert client.get(f"/documents/{source.id}/{labs}/2").status_code == 404
    assert client.get(f"/documents/unknown/{labs}/1").status_code == 404
    assert f'href="/documents/{source.id}/{labs}/1"' in listing and "transcribed" in listing
    assert '<span class="file-id"' in listing and labs[:8] in listing and labs[:8] in card.text


def test_file_id_colour_follows_share_of_text_read():
    from epicrisis.web.documents import file_reading, reading_colour

    rows = [{"goes_to_extract": True, "pages": [1, 2]}, {"goes_to_extract": True, "pages": [3]}]
    extracted = {"documents": [{
        "pages": [1, 2],
        "page_texts": [{"page": 1, "text": "line one\nline two\n\nline three"}, {"page": 2, "text": "only line"}],
        "unreadable": [{"page": 1, "what": "value", "why": "blurred"}],
    }]}  # fmt: skip

    reading = file_reading(extracted, rows, error_pages=[4])

    # Page 1: 3 of 4, page 2: all, page 4 could not be opened: (0.75 + 1 + 0) / 3.
    assert reading["percent"] == 58
    assert reading["title"] == (
        "Text read: 58% over 3 pages, 1 part could not be read, 1 page could not be opened; 1 of 2 documents transcribed so far"
    )
    assert file_reading(None, rows, [])["percent"] is None
    assert reading_colour(1)["background"] == "hsl(130, 62%, 34%)"
    assert reading_colour(0)["background"] == "hsl(348, 78%, 40%)"
    assert reading_colour(0.99)["background"] != reading_colour(1)["background"]


def test_card_lays_out_results_as_the_printed_tables(setup):
    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]
    document = load_extracted(output / "extracted", labs)["documents"][0]
    first = document["observations"][0]
    printed = {"table_as_printed": "White Cell Differentials", "reference_column_as_printed": "Normal Values"}
    document["observations"] = [
        # The other column may come first: the row still leads with the result.
        {**first, **printed, "value_role": "other", "column_as_printed": "Absolute", "value_as_printed": "2,82", "unit_as_printed": "x10^3/L", "reference_as_printed": None},
        {**first, **printed, "value_role": "result", "column_as_printed": "Result", "value_as_printed": "58,3", "unit_as_printed": "%"},
        *[{**item, "value_role": "result", "table_as_printed": "Biochemistry"} for item in document["observations"][1:]],
    ]  # fmt: skip
    write_document(output / "extracted", labs, document)

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    card = client.get(f"/documents/{source.id}/{labs}/1").text

    assert card.count('class="obs-table-title"') == 2 and "White Cell Differentials" in card
    head = card[card.index("White Cell Differentials") : card.index("Analyte 1</span>")]
    assert "Result<small>result</small>" in head and "Normal Values<small>reference range</small>" in head
    assert "Absolute<small>other value</small>" in head
    assert card.count("Analyte 1</span>") == 1
    row = card[card.index("Analyte 1</span>") :]
    row = row[: row.index('class="page-links"')]
    assert row.index("58,3") < row.index("4,0-9,0") < row.index("2,82 x10^3/L")


class SloppyBackend(FakeExtractBackend):
    """A small model that adds a character the page does not print to every value."""

    def extract(self, payloads, workdir: Path) -> Extraction:
        extraction = super().extract(payloads, workdir)
        for item in extraction.fields["observations"]:
            item["value_as_printed"] += "?"
        return extraction


def test_ladder_moves_to_the_stronger_model_only_when_a_check_fails(setup):
    from epicrisis.extract.backend import ExtractLadder

    data_dir, source, output, records = setup
    clean_small, unused = FakeExtractBackend(model="fake-haiku"), FakeExtractBackend(model="fake-opus")
    assert extract_source(data_dir, source, ExtractLadder(clean_small, unused), years={2003}).escalated == 0
    assert unused.calls == [] and len(clean_small.calls) == 2

    # The text document: the small model's values are not in the text that was sent.
    small, strong = SloppyBackend(model="fake-haiku"), FakeExtractBackend(model="fake-opus")
    stats = extract_source(data_dir, source, ExtractLadder(small, strong), years={2019})

    assert (stats.extracted, stats.escalated, len(small.calls), len(strong.calls)) == (1, 1, 1, 1)
    document = load_extracted(output / "extracted", records["labs.pdf"]["sha256"])["documents"][0]
    assert document["provenance"]["requested_model"] == "fake-opus"
    assert document["provenance"]["escalations"][0]["problems"]["value_not_in_page_text"] == 2
    assert all("?" not in item["value_as_printed"] for item in document["observations"])

    again = ExtractLadder(FakeExtractBackend(model="fake-haiku"), FakeExtractBackend(model="fake-opus"))
    assert extract_source(data_dir, source, again).already_done == 2


def test_documents_done_by_the_strong_model_alone_count_as_done_for_the_ladder(setup):
    from epicrisis.extract.backend import ExtractLadder

    data_dir, source, _, _ = setup
    extract_source(data_dir, source, FakeExtractBackend(model="fake-opus"))
    small = FakeExtractBackend(model="fake-haiku")

    assert extract_source(data_dir, source, ExtractLadder(small, FakeExtractBackend(model="fake-opus"))).already_done == 2
    assert small.calls == []


def test_text_pages_are_checked_against_the_text_that_was_sent():
    from epicrisis.extract.run import transcription_problems

    item = {"name_as_printed": "Analyte", "value_as_printed": "6,8", "reference_as_printed": "4,0 - 9,0", "value_numeric": 6.8, "provenance": {"page": 1}}
    document = {"doc_type": "lab_panel", "pages": [1], "unreadable": [], "page_texts": [{"page": 1, "text": "Analyte 6,8 Normal g/L 4,0-9,0 transcribed"}],
                "observations": [dict(item, column_as_printed="Result"), dict(item, value_as_printed="6,8 Normal", column_as_printed="Result")]}  # fmt: skip

    assert transcription_problems(document, {1: "Analyte 6,8 Normal g/L 4,0-9,0"}) == {}
    assert transcription_problems(document, {1: "Analyte 6,3 g/L 4,0-9,0"}) == {"value_not_in_page_text": 2}

    other_names = [dict(item, name_as_printed=f"Analyte {n}") for n in (1, 2)]
    single = dict(document, observations=other_names)
    assert transcription_problems(single, {1: "Analyte 6,8 g/L 4,0-9,0"}) == {}
    same_row = dict(document, observations=[dict(item, name_as_printed="Analyte"), dict(item, name_as_printed="Analyte", value_role="other")])
    assert transcription_problems(same_row, {1: "Analyte 6,8 g/L 4,0-9,0"}) == {"no_column_headings_in_multi_value_rows": 1}


def test_a_birth_date_given_as_the_study_date_fails_the_check():
    from epicrisis.extract.run import transcription_problems

    document = {"doc_type": "consultation", "pages": [1], "unreadable": [], "language": "es", "observations": [],
                "date_of_study_as_printed": "06.12.61", "date_of_report_as_printed": "19 de junio de 2023",
                "page_texts": [{"page": 1, "text": "Fecha de nacimiento: 06.12.61"}]}  # fmt: skip
    assert transcription_problems(document, {}) == {"document_date_is_birth_date": 1}


def test_date_search_fills_a_missing_date_and_never_a_birth_date(setup):
    from epicrisis.datesearch import load_search_results, search_source
    from epicrisis.document_dates import document_date

    data_dir, source, output, records = setup

    class FakeSearch:
        name, model = "fake", "fake-opus"
        calls = []

        def search(self, images, workdir):
            FakeSearch.calls.append([(page.name, [path.name for path in close_ups], page.exists()) for page, close_ups in images])
            return [
                {"as_printed": "06.12.61", "page": 1, "kind": "birth", "label_as_printed": "DOB", "legible": True},
                {"as_printed": "08.09.21", "page": 2, "kind": "stamp", "label_as_printed": None, "legible": True},
            ], "fake-opus-2026"

    scan = records["long_scan.pdf"]
    stats = search_source(data_dir, source, FakeSearch(), [(scan, tuple(range(1, 11)))], workers=2)

    assert (stats.searched, stats.with_dates) == (1, 1)
    assert [len(call) for call in FakeSearch.calls] == [3, 3, 3, 1]
    assert FakeSearch.calls[0][0][1] == [f"{scan['sha256'][:16]}-01{part}.png" for part in "abcd"] and FakeSearch.calls[0][0][2]
    result = load_search_results(output)[(scan["sha256"], tuple(range(1, 11)))]
    assert sorted({item["page"] for item in result["found"]}) == [1, 2, 4, 5, 7, 8, 10]

    chosen = document_date(None, [{"language": "ru", "date_on_page": None}], search=result)
    assert (chosen["label"], [flag["code"] for flag in chosen["flags"]]) == ("08.09.2021", ["second_look"])
    assert search_source(data_dir, source, FakeSearch(), [(scan, tuple(range(1, 11)))]).total == 0


def test_validation_lists_findings_without_changing_data(setup, monkeypatch):
    from epicrisis.validate import validate_source

    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]
    stored = load_extracted(output / "extracted", labs)
    document = stored["documents"][0]
    first = document["observations"][0]
    document["observations"] = [
        dict(first, value_as_printed=",5", value_numeric=0.5, value_role="result"),
        dict(first, name_as_printed="Other", value_as_printed="12,3", value_numeric=1.23, value_role="result"),
        dict(first, name_as_printed="Sign", value_as_printed="<0,5", value_numeric=0.5, comparator=None, value_role="result"),
        dict(first, name_as_printed="Words", value_as_printed="up to 5", value_numeric=5, comparator="<=", value_role="result"),
        dict(first, name_as_printed="Range", reference_as_printed="9,0 - 4,0", value_role="result"),
        dict(first, name_as_printed="Only other", value_role="other"),
    ]
    write_document(output / "extracted", labs, document)
    before = {path.name: path.read_bytes() for path in output.rglob("*") if path.is_file()}

    result = validate_source(output)

    finding = next(item for item in result["documents"] if item["file_sha256"] == labs)["findings"]
    assert finding.items() >= {"number_differs": 1, "comparator_missing": 1, "reference_reversed": 1, "row_without_result": 1}.items()
    assert "repeated_value" not in finding and "quantitative_without_number" not in finding
    after = {path.name: path.read_bytes() for path in output.rglob("*") if path.is_file() and path.name != "validation.json"}
    assert after == before

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/review").text
    assert "The number stored differs from the value as printed" in page and labs[:8] in page
    assert page.index("The number stored differs") < page.index("A row has other values but no result")
    card = client.get(f"/documents/{source.id}/{labs}/1").text
    assert "To check" in card and "The reference range has its lower bound above the upper bound" in card
    assert client.post(f"/sources/{source.id}/validate", follow_redirects=False).status_code == 303


def test_printed_forms_that_are_not_mismatches():
    from epicrisis.extract.run import transcription_problems

    def observation(value, numeric, reference=None, comparator=None):
        return {"name_as_printed": "A", "value_as_printed": value, "value_numeric": numeric, "reference_as_printed": reference,
                "comparator": comparator, "provenance": {"page": 1}, "column_as_printed": "Result"}  # fmt: skip

    page = "Нв- I00г/л РОЭ до 17 мм Сечова к-та 0,39 Ч. 0,20-0,42 мМ/л\nЖ. 0,14-0,34 мМ/л *5,23 [3,9 - 5,2]"
    document = {"doc_type": "lab_panel", "pages": [1], "unreadable": [], "language": "uk", "page_texts": [{"page": 1, "text": page}],
                "observations": [observation("I00", 100), observation("до 17", 17, comparator="<="),
                                 observation("0,39", 0.39, reference="Ч. 0,20-0,42 мМ/л Ж. 0,14-0,34 мМ/л")]}  # fmt: skip
    assert transcription_problems(document, {}) == {}

    document["observations"] = [observation("5,23", 5.23, reference="3,9 - 5,2", comparator=">")]
    assert transcription_problems(document, {}) == {"comparator_not_printed": 1}


def test_index_holds_documents_values_dates_and_folded_search(setup):
    import sqlite3
    from datetime import date

    from epicrisis.corrections import set_document_date
    from epicrisis.index.build import build_index, fold, index_state
    from epicrisis.validate import validate_source

    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]
    document = load_extracted(output / "extracted", labs)["documents"][0]
    document["observations"][0]["name_as_printed"] = "Креатинін"
    document["diagnoses_as_printed"] = ["Κάταγμα"]
    write_document(output / "extracted", labs, document)
    set_document_date(output, labs, [1, 2], date(2019, 5, 17))
    validate_source(output)

    totals = build_index(data_dir, [source])
    connection = sqlite3.connect(index_path(data_dir, source.id))
    query = lambda sql, *args: connection.execute(sql, args).fetchall()

    assert (totals["documents"], totals["transcribed"]) == (3, 2)
    assert query("SELECT date, date_by_hand, transcribed FROM documents WHERE file_sha256 = ?", labs) == [("2019-05-17", 1, 1)]
    assert query("SELECT transcribed FROM documents WHERE file_sha256 = ?", records["invoice.pdf"]["sha256"]) == [(0,)]
    assert query("SELECT kind, count(*) FROM observations GROUP BY kind") == [("analyte", 2), ("measurement", 10)]
    found = lambda term: query("SELECT d.file_sha256 FROM search JOIN documents d ON d.id = search.rowid WHERE search MATCH ?", fold(term) + "*")
    assert found("креатинин") == [(labs,)] and found("КРЕАТИНІН") == [(labs,)] and found("καταγμα") == [(labs,)]
    assert fold("Κρεατινίνη") == "κρεατινινη"
    assert index_state(data_dir, output, source.id)["state"] == "done"
    connection.close()


def test_a_transcription_that_stops_early_fails_the_check():
    from epicrisis.extract.run import transcription_problems

    sent = {page: " ".join(f"word{n} 1{n},5" for n in range(60)) for page in (1, 2, 3)}
    document = {"doc_type": "lab_panel", "pages": [1, 2, 3], "unreadable": [], "language": "es",
                "page_texts": [{"page": 1, "text": sent[1]}, {"page": 2, "text": "word1 11,5 word2 12,5 word3 13,5"}],
                "observations": [{"name_as_printed": "word1", "value_as_printed": "11,5", "value_numeric": 11.5, "reference_as_printed": None,
                                  "comparator": None, "provenance": {"page": 1}, "column_as_printed": "Resultado"}]}  # fmt: skip

    assert transcription_problems(document, sent, tabular_pages=(1, 3)) == {
        "page_text_short": 1, "page_text_missing": 1, "table_page_without_values": 1,
    }  # fmt: skip


def test_copies_include_short_documents_and_excerpts_and_derived_values_are_marked(setup):
    import sqlite3
    from datetime import date

    from epicrisis.corrections import set_document_date
    from epicrisis.index.build import build_index
    from epicrisis.validate import validate_source

    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs, scan = records["labs.pdf"]["sha256"], records["long_scan.pdf"]["sha256"]
    for sha, pages, observations in (
        # The short lab excerpt prints three results that all appear, in capitals, in the long report.
        (labs, [1, 2], [("Цистатин С", "0,95", "мг/л"), ("ШКФ (CKD-EPI)", "101", "мл/хв"), ("Креатинін:", "71", "мкмоль/л")]),
        (scan, list(range(1, 11)), [("ЦИСТАТИН С", "0,95", "мг/л"), ("ШКФ (CKD-EPI)", "101", "мл/хв"), ("КРЕАТИНІН", "71", "мкмоль/л"), ("Сечовина", "5,1", "ммоль/л")]),
    ):
        document = load_extracted(output / "extracted", sha)["documents"][0]
        template = document["observations"][0]
        document["observations"] = [dict(template, name_as_printed=n, value_as_printed=v, unit_as_printed=u, table_as_printed=None) for n, v, u in observations]
        write_document(output / "extracted", sha, document)
        set_document_date(output, sha, pages, date(2024, 6, 17))

    result = validate_source(output)
    build_index(data_dir, [source])
    connection = sqlite3.connect(index_path(data_dir, source.id))

    finding = next(item for item in result["documents"] if item["file_sha256"] == labs)
    assert finding["copies"] == [{"file_sha256": scan, "pages": list(range(1, 11))}]
    assert connection.execute("SELECT count(DISTINCT copy_group), sum(primary_copy) FROM documents WHERE copy_group IS NOT NULL").fetchone() == (1, 1)
    assert connection.execute("SELECT name, derived FROM observations WHERE derived = 1").fetchall() == [("ШКФ (CKD-EPI)", 1), ("ШКФ (CKD-EPI)", 1)]
    connection.close()


def test_update_runs_every_step_and_skips_what_is_done(setup, monkeypatch):
    from epicrisis import update as update_module
    from epicrisis.consent import record_consent

    data_dir, source, output, records = setup
    record_consent(data_dir, "fake")

    class Search:
        name, model = "fake", "fake-opus"
        def __init__(self, model=None):
            self.model = model or self.model
        def search(self, images, workdir):
            return [], "fake-opus"

    classify_calls = []

    class Classify:
        name, model = "fake", "fake-haiku"
        def __init__(self, model=None):
            self.model = model or self.model
        def classify(self, payload, workdir):
            classify_calls.append(1)
            raise AssertionError("classify.jsonl already covers every page")

    # Every step asks epicrisis.engines for something that can read; the test answers instead.
    class FakeLadder:
        def __init__(self, first=None):
            self.name, self.model, self.accepted_models = "fake", "fake-ladder", {"fake-ladder"}

    monkeypatch.setattr(update_module.engines, "classifier", lambda *args: FakeLadder(Classify()))
    monkeypatch.setattr(update_module.engines, "extractor", lambda *args: FakeExtractBackend())
    monkeypatch.setattr(update_module.engines, "date_search", lambda *args: Search())

    # classify.jsonl in the fixture has no ledger and one route for all pages: make both match inventory.
    routes = {(ref.file_sha256, ref.page): ref.route for record in records.values() for ref in page_refs(record)}
    lines = [dict(line, route=routes[(line["file_sha256"], line["page"])]) for line in read_records(output / "classify.jsonl")]
    (output / "classify.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    ledger = output / "ledger.jsonl"
    with ledger.open("a") as fh:
        for line in lines:
            fh.write(json.dumps({"step": "classify", "file_sha256": line["file_sha256"], "page": line["page"], "model": "fake-ladder",
                                 "prompt_version": __import__("epicrisis.classify.backend", fromlist=["PROMPT_VERSION"]).PROMPT_VERSION,
                                 "status": "done", "at": "2026-01-01T00:00:00+00:00"}) + "\n")  # fmt: skip

    said = []
    first = update_module.run_update(data_dir, say=said.append)
    second = update_module.run_update(data_dir, say=said.append)

    assert classify_calls == [] and first["transcribed"] == 2 and second["documents"] == first["documents"]
    assert any("extract: 2 new documents" in line for line in said) and any("extract: 0 new documents" in line for line in said)
    assert index_path(data_dir, source.id).exists() and not (data_dir / "update.lock").exists()


def test_a_person_corrects_a_value_and_marks_a_line_as_not_a_value(setup):
    import sqlite3

    from epicrisis.index.build import build_index

    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]
    document = load_extracted(output / "extracted", labs)["documents"][0]
    template = document["observations"][0]
    document["observations"] = [
        dict(template, name_as_printed="Креатинін", value_as_printed="7I", unit_as_printed="мкмоль/л"),
        dict(template, name_as_printed="P1", value_as_printed="42", unit_as_printed=None),
    ]
    write_document(output / "extracted", labs, document)
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    url = f"/documents/{source.id}/{labs}/1"

    card = client.get(url).text
    assert "Correct this line" in card and "Not a value" in card
    key = card.split('name="key" value="')[1].split('"')[0]

    client.post(f"{url}/value", data={"key": key, "name": "Креатинін", "value": "71", "unit": "мкмоль/л", "reference": "", "flag": ""})
    corrected = client.get(url).text
    assert ">71<" in corrected and "corrected" in corrected and "As the model read it: Креатинін &middot; 7I" in corrected

    junk_key = corrected.split('name="key" value="')[2].split('"')[0]
    client.post(f"{url}/value", data={"key": junk_key, "action": "remove"})
    assert "not a value" in client.get(url).text

    build_index(data_dir, [source])
    connection = sqlite3.connect(index_path(data_dir, source.id))
    stored = connection.execute("SELECT name, value, corrected FROM observations ORDER BY id").fetchall()
    connection.close()
    assert ("Креатинін", "71", 1) in stored and not any(row[0] == "P1" for row in stored)

    client.post(f"{url}/value", data={"key": key, "action": "reset"})
    assert "7I" in client.get(url).text


def test_one_file_can_be_read_again_on_demand_with_close_ups(setup):
    """A person points at a file and asks for another reading; the rest of the archive is left alone."""
    data_dir, source, output, records = setup
    extract_source(data_dir, source, UnreadableBackend(whole_page=1, close_up=1))
    text_file = records["labs.pdf"]["sha256"]
    # The text document kept its unreadable part: it went as text, so no close-ups were offered.
    assert load_extracted(output / "extracted", text_file)["documents"][0]["unreadable"]

    untouched = scan_document(output, records)["provenance"]
    again = UnreadableBackend(whole_page=1, close_up=0)
    stats = extract_source(data_dir, source, again, files={text_file[:8]}, redo=True, close_ups=True, workers=1)

    assert (stats.extracted, stats.already_done, stats.close_up_passes) == (1, 0, 1)
    document = load_extracted(output / "extracted", text_file)["documents"][0]
    assert document["unreadable"] == [] and document["provenance"]["close_up_pass"]["status"] == "kept"
    # The scan was not touched: its transcription is still the one from the first run.
    assert scan_document(output, records)["provenance"] == untouched


def test_an_institution_read_as_the_signing_doctor_fails_the_check(setup):
    """The name under the stamp is not the laboratory: the check sends the page to the strong model."""
    from epicrisis.extract.run import mixed_script_words, transcription_problems

    document = {
        "doc_type": "lab_panel", "pages": [1], "provider_as_printed": "Соловьёв А.И.", "title_as_printed": "Кліnіка VITAMED",
        "page_texts": [{"page": 1, "text": "Соловьёв А.И. Кліnіка VITAMED " + "word " * 30}], "observations": [], "unreadable": [],
    }  # fmt: skip
    problems = transcription_problems(document, {})

    assert problems["institution_looks_like_a_name"] == 1 and problems["word_in_two_alphabets"] == 1
    assert mixed_script_words("Кліnіка VITAMED") == ["Кліnіка"] and mixed_script_words("Клініка VITAMED") == []

    named = dict(document, provider_as_printed="«ПОЛІДІАГНОСТИКА»", title_as_printed="Клініка VITAMED")
    named["page_texts"] = [{"page": 1, "text": "«ПОЛІДІАГНОСТИКА» Клініка VITAMED " + "word " * 30}]
    assert transcription_problems(named, {}) == {}


def test_a_correction_names_the_file_by_its_whole_hash(setup):
    """A correction against a shortened file id matches nothing, and nothing is the worst answer."""
    import pytest

    from epicrisis.corrections import load_value_corrections, set_value, value_key

    data_dir, source, output, records = setup
    labs = records["labs.pdf"]["sha256"]
    key = value_key(1, "Креатинін", "95,4")

    with pytest.raises(ValueError, match="whole sha256"):
        set_value(output, labs[:16], (1,), key, {"value_as_printed": "75,4"})

    set_value(output, labs, (1,), key, {"value_as_printed": "75,4"})
    assert load_value_corrections(output)[(labs, (1,), key)]["changes"] == {"value_as_printed": "75,4"}


def test_a_correction_outlives_a_second_reading_by_a_model(setup):
    """The promise behind every correction: reading the page again does not undo a person's work."""
    import sqlite3

    from epicrisis.corrections import set_value, value_key
    from epicrisis.index.build import build_index

    data_dir, source, output, records = setup
    # One worker, so the fake model numbers its answers the same way in both readings.
    extract_source(data_dir, source, FakeExtractBackend(), workers=1)
    labs = records["labs.pdf"]["sha256"]
    document = load_extracted(output / "extracted", labs)["documents"][0]
    first = document["observations"][0]
    key = value_key(first["provenance"]["page"], first["name_as_printed"], first["value_as_printed"])
    set_value(output, labs, tuple(document["pages"]), key, {"value_as_printed": "7,1"})

    # A model reads the whole document again, as it does when a prompt or a model changes.
    extract_source(data_dir, source, FakeExtractBackend(), files={labs[:8]}, redo=True, workers=1)
    build_index(data_dir, [source])

    connection = sqlite3.connect(index_path(data_dir, source.id))
    # That file only: the same synthetic names appear in the other documents of this archive.
    corrected = connection.execute(
        """SELECT o.value, o.corrected FROM observations o JOIN documents d ON d.id = o.document_id
           WHERE d.file_sha256 = ? AND o.name = ? ORDER BY o.id""",
        (labs, first["name_as_printed"]),
    ).fetchone()  # fmt: skip
    connection.close()
    assert corrected == ("7,1", 1)


def test_a_correction_that_lost_its_line_is_counted_not_forgotten(setup):
    """Silence is the failure here: a person's own reading applying to nothing, with no sign of it."""
    from epicrisis.corrections import set_value, unmatched_values, value_key

    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]
    document = load_extracted(output / "extracted", labs)["documents"][0]
    first = document["observations"][0]
    pages = tuple(document["pages"])
    set_value(output, labs, pages, value_key(first["provenance"]["page"], first["name_as_printed"], first["value_as_printed"]), {"value_as_printed": "7,1"})
    assert unmatched_values(output) == []

    # A model reads the line differently than it did when the person corrected it.
    document["observations"][0] = {**first, "value_as_printed": "6,9"}
    write_document(output / "extracted", labs, document)

    lost = unmatched_values(output)
    assert len(lost) == 1 and lost[0]["pages"] == list(pages) and lost[0]["changes"] == {"value_as_printed": "7,1"}


def test_a_value_that_is_nowhere_on_its_page_is_a_finding_of_its_own():
    """A page of real text is the page itself. A number not in it was not printed there.

    This is the one way a document can lie to the archive from outside: text on the page telling
    the model what to write. The reading cannot be trusted to catch it, so the text is compared
    with what came back.
    """
    from epicrisis.extract.run import transcription_problems

    page = (
        "Northfield Medical Laboratory. Full blood count. "
        "Haemoglobin 134 g/L 120-150. Red cells 4.41 10*12/L 3.9-4.7. White cells 6.1 10*9/L 4.0-9.0. "
        "Platelets 248 10*9/L 150-400. Creatinine 71 umol/L 53-97. Glucose 5.0 mmol/L 3.9-5.8. "
        "Reported by the laboratory on the twelfth of May, two thousand and twenty, in the afternoon."
    )
    document = {
        "doc_type": "lab_panel", "pages": [1], "provider_as_printed": "Northfield Medical Laboratory",
        "title_as_printed": "Full blood count", "unreadable": [],
        "page_texts": [{"page": 1, "text": page}],
        "observations": [
            {"name_as_printed": "Haemoglobin", "value_as_printed": "134", "value_kind": "quantitative",
             "provenance": {"page": 1}},
            {"name_as_printed": "Haemoglobin", "value_as_printed": "3,1", "value_kind": "quantitative",
             "provenance": {"page": 1}},
        ],
    }  # fmt: skip

    problems = transcription_problems(document, {1: page}, (1,))

    assert problems.get("value_not_on_the_page") == 1

    # A scan has no text of its own to check against, and a qualitative answer is not a number.
    assert "value_not_on_the_page" not in transcription_problems(document, {}, (1,))
    words = dict(document, observations=[dict(document["observations"][1], value_kind="qualitative")])
    assert "value_not_on_the_page" not in transcription_problems(words, {1: page}, (1,))
