"""Where one document ends and the next begins in a file that is nothing but text.

Every file here is invented and written at test time.
"""

import json
import pathlib
from pathlib import Path

from epicrisis.boundaries import (
    PROMPT_VERSION,
    cuts_in,
    find_boundaries,
    pages_of,
    read_boundaries,
    where_it_begins,
    windows,
)
from epicrisis.classify.pages import page_refs
from epicrisis.classify.report import group_documents
from epicrisis.readers.text import TEXT_PAGE_CHARS
from epicrisis.inventory.run import write_inventory
from epicrisis.records import read_records

# Long enough to be two documents rather than two lines: two cuts closer than a few hundred
# characters are one cut, which is how a heading quoted twice is kept from splitting a document.
A_VISIT = ("КОНСУЛЬТАЦІЯ ЛІКАРЯ\nДата: 12.05.2021\nГемоглобін 134 г/л\n"
           + "скарги та призначення, рядок опису\n" * 20)  # fmt: skip
ANOTHER = ("ВИПИСКА З ІСТОРІЇ ХВОРОБИ\nДата: 07.11.2025\nЛейкоцити 6,3\n"
           + "перебіг та рекомендації, рядок опису\n" * 20)  # fmt: skip


class FakeBoundaries:
    """Answers with the lines it was told to, and counts what it was asked."""

    name = "fake-backend"
    model = "fake-haiku"

    def __init__(self, lines: list[str] | None = None, chooses: str = "none"):
        self.lines = lines or []
        self.chooses = chooses  # the letter of the candidate separator, or "none"
        self.calls: list[str] = []
        self.asked_which: list[str] = []

    def call(self):
        backend = self

        class Call:
            def ask(self, system, schema, request, workdir):
                backend.asked_which.append(request)
                return {"which": backend.chooses, "why": "a test"}, backend.model

        return Call()

    def read(self, text: str, workdir: Path) -> dict:
        self.calls.append(text)
        return {"documents": [{"first_line": line, "kind": "other", "date_as_printed": None}
                              for line in self.lines if line in text]}  # fmt: skip


def test_windows_overlap_so_a_document_on_the_edge_is_seen_whole():
    text = "".join(f"line {number}\n" for number in range(4000))
    pieces = windows(text, size=1000, overlap=100)

    assert pieces[0][0] == 0
    assert all(start == number * 900 for number, (start, _) in enumerate(pieces))
    assert "".join(piece[:900] for _, piece in pieces) == text  # nothing between two windows
    assert all(len(piece) <= 1000 for _, piece in pieces)
    assert windows("") == []


def test_a_line_this_program_cannot_find_in_the_file_is_not_a_boundary():
    """A boundary is a place in the file. One that cannot be pointed at does not exist."""
    text = "первая строка\nВИПИСКА  З  ІСТОРІЇ\nещё строка\n"

    assert where_it_begins("ВИПИСКА  З  ІСТОРІЇ", text, 0, text) == len("первая строка\n")
    # The one liberty a model takes with a line it copies: the spaces inside it.
    assert where_it_begins("ВИПИСКА З ІСТОРІЇ", text, 0, text) == len("первая строка\n")
    assert where_it_begins("ВЫПИСКА ИЗ ИСТОРИИ", text, 0, text) is None  # translated, not quoted
    assert where_it_begins("", text, 0, text) is None
    assert where_it_begins("ещё строка", text, 100, text) == 100 + text.index("ещё строка")


def test_cuts_start_at_nought_and_count_what_was_not_found():
    text = A_VISIT + ANOTHER
    answers = [(0, text, {"documents": [
        {"first_line": "ВИПИСКА З ІСТОРІЇ ХВОРОБИ"},
        {"first_line": "a line that is not in this file at all"},
    ]})]  # fmt: skip

    cuts, lost = cuts_in(text, answers)

    assert cuts == [0, len(A_VISIT)]  # the file begins with whatever its first document is
    assert lost == 1

    # A heading and its own first line, quoted twice, are one cut.
    twice = [(0, text, {"documents": [{"first_line": "ВИПИСКА З ІСТОРІЇ ХВОРОБИ"}, {"first_line": "Дата: 07.11.2025"}]})]
    assert cuts_in(text, twice)[0] == [0, len(A_VISIT)]


def test_a_document_longer_than_a_page_is_cut_at_line_ends_and_stays_one_document():
    long_one = "рядок результату 12,3 г/л\n" * 800
    text = A_VISIT + long_one
    pages = pages_of(text, [0, len(A_VISIT)])

    assert [number for _, number in pages][0] == 0
    assert {number for _, number in pages} == {0, 1}
    assert len([page for page, number in pages if number == 1]) > 1  # cut further, one document
    assert all(len(page) <= TEXT_PAGE_CHARS for page, _ in pages)
    assert "".join(page for page, _ in pages) == text  # nothing lost between the pages


def test_a_file_that_fences_its_documents_is_cut_where_it_fences_them(tmp_path):
    """A text export is written by a machine, and a machine draws a line between its documents.

    Measured on the first such archive: it fences its records with "====Department====", 256 of
    them. Walking it in windows and asking a model to quote the first line of every document found
    67 of those 256, missed 189, and cut 16 times inside a document. What a machine wrote down
    plainly is not worth guessing at — the model is asked one thing, which of the candidate lines
    begins documents, and the counting is this program's own.
    """
    from epicrisis.boundaries import candidate_separators, find_boundaries

    body = "рядок результату 12,3 г/л\n" * 60  # a document, not a paragraph
    text = "".join(f"===============Відділення  {name}===============\nДата: 0{n}.03.2026\n{body}"
                   for n, name in enumerate(("Лабораторія", "Урологічне", "Терапевтичне", "Лабораторія"), 1))  # fmt: skip
    root = tmp_path / "archive"
    root.mkdir()
    (root / "history.txt").write_text(text, encoding="utf-8")
    output = tmp_path / "out"
    output.mkdir()
    write_inventory(root, output / "inventory.jsonl")
    record = next(read_records(output / "inventory.jsonl"))

    candidates = candidate_separators(text)
    assert candidates[0][0] == "a rule of ="  # the same fence with another word in it is one shape
    assert len(candidates[0][1]) == 4

    backend = FakeBoundaries(chooses="A")
    cuts = find_boundaries(output, record, root, backend)

    assert len(cuts) == 4 and cuts[0] == 0
    assert all(text[at - 1] == "\n" for at in cuts[1:])  # on the fence, not inside a line
    assert backend.calls == []  # nothing was asked to read the file; one question, about the lines
    line = json.loads((output / "boundaries.jsonl").read_text().splitlines()[0])
    assert line["found_by"] == "separator" and line["documents"] == 4


def _the_version_if(name: str, value) -> str:
    """The module's own version of its questions, worked out as if one name stood differently.

    The module's source, read and run in a namespace of its own with that one line replaced.
    PROMPT_VERSION is settled at import and is what the records carry, so the question "would this
    have been a different version" cannot be asked of the module that is already loaded — and
    asking it of a copy of the source is the one way of asking it that does not depend on how the
    version happens to be computed.
    """
    import re

    import epicrisis.boundaries as boundaries

    stands = getattr(boundaries, name)
    source = pathlib.Path(boundaries.__file__).read_text(encoding="utf-8")
    if isinstance(stands, str):
        # A prompt is a triple-quoted block, so what is replaced is the text itself where it
        # stands in the file, and not the line the name is assigned on.
        changed, how_many = source.replace(stands, value, 1), source.count(stands)
    else:
        changed, how_many = re.subn(rf"(?m)^{name} = .*$", f"{name} = {value!r}", source, count=1)
    assert how_many == 1, f"{name} does not stand once and plainly in boundaries.py"
    space: dict = {"__name__": "boundaries_as_if_one_number_stood_differently", "__file__": boundaries.__file__}
    exec(compile(changed, boundaries.__file__, "exec"), space)  # noqa: S102
    return space["PROMPT_VERSION"]


def test_the_version_of_the_markup_covers_every_question_it_asks():
    """A markup kept from before is taken as it stands, so the version has to cover all of it.

    The question about the fences was left out of it once, and the step answered a file it had
    never looked at with the walk it had done an hour before — 83 cuts where the file has 256.
    Four of the numbers that decide where the cuts land were left out of it as well: the distance
    at which two cuts are one cut, the overlap that decides whether either of two windows sees a
    document beginning on their seam, the floor under halving a window, and the floor for
    accepting a separator at all — which was a default argument in a signature, outside anything
    that counted the questions.

    What stood here could not have failed: it asserted that three prompts were each inside the
    three of them joined together, and that str(RULE_RUN) was a non-empty string.
    """
    import epicrisis.boundaries as boundaries

    version = boundaries.PROMPT_VERSION
    assert len(version) == 12 and version == boundaries.prompt_version()
    for name in boundaries.CUTTING_NUMBERS:
        assert _the_version_if(name, getattr(boundaries, name) + 1) != version, name
    for name in ("SYSTEM_PROMPT", "REQUEST", "SEPARATOR_PROMPT", "SEPARATOR_REQUEST"):
        assert _the_version_if(name, getattr(boundaries, name) + " One more sentence.") != version, name


def test_no_number_that_decides_where_a_file_is_cut_stands_outside_the_version():
    """The next number added to this module, and not only the four that were missing from it.

    Every number named in this module that the cutting reads, and every number standing as a
    default in one of their signatures, has to be one the version is made of. `least = 1_000`
    decided whether a separator was accepted at all and sat in a signature, where nothing counting
    the questions asked of a file could see it; the same question's other floor was a named
    constant inside the version, two lines away.
    """
    import inspect
    import re

    import epicrisis.boundaries as boundaries

    deciding = (boundaries.separator_shapes, boundaries.candidate_separators,
                boundaries.lettered_stretches, boundaries._pieces_look_like_documents,
                boundaries.choose_separator, boundaries.windows, boundaries.where_it_begins,
                boundaries.cuts_in, boundaries.find_boundaries)  # fmt: skip
    source = "\n".join(inspect.getsource(one) for one in deciding)
    named = {name for name, value in vars(boundaries).items() if name.isupper() and type(value) is int}
    read = {name for name in named if re.search(rf"\b{name}\b", source)}
    assert read, "the cutting reads none of this module's numbers, which cannot be right"
    assert read <= set(boundaries.CUTTING_NUMBERS), read - set(boundaries.CUTTING_NUMBERS)

    # And a default is read as it is written, not as what it comes to: a number written out in a
    # signature is a number nothing can count, whatever named constant happens to hold it too.
    import ast
    import textwrap

    for one in deciding:
        written = ast.parse(textwrap.dedent(inspect.getsource(one))).body[0]
        for given in written.args.defaults + [one for one in written.args.kw_defaults if one]:
            assert not (isinstance(given, ast.Constant) and type(given.value) is int), \
                f"{written.name}: {given.value} stands as a default where nothing counting the questions sees it"
            if isinstance(given, ast.Name) and type(getattr(boundaries, given.id, None)) is int:
                assert given.id in set(boundaries.CUTTING_NUMBERS), f"{written.name}: {given.id}"


def test_a_separator_that_leaves_paragraphs_rather_than_documents_is_refused(tmp_path):
    """The one judgement of this step can go wrong, and a wrong one is caught by counting.

    Asked about the archive this was built for, a model first chose the rule dividing a record's
    heading from its body: four hundred and fifty pieces of seven hundred characters, which are
    not four hundred and fifty documents.
    """
    from epicrisis.boundaries import _pieces_look_like_documents, find_boundaries

    # Pieces of about five hundred characters: long enough to be offered as a candidate, far too
    # short to be documents.
    text = ("====Відділення  Лабораторія====\nДата: 01.03.2026\n"
            + ("----------------\n" + "рядок результату 12,3 г/л\n" * 19) * 8) * 3  # fmt: skip
    root = tmp_path / "archive"
    root.mkdir()
    (root / "history.txt").write_text(text, encoding="utf-8")
    output = tmp_path / "out"
    output.mkdir()
    write_inventory(root, output / "inventory.jsonl")
    record = next(read_records(output / "inventory.jsonl"))

    dashes, offset = [], 0
    for line in text.split("\n"):
        if line.startswith("----"):
            dashes.append(offset)
        offset += len(line) + 1
    assert 200 <= len(text) / len(dashes) < 1_000  # offered as a candidate, and not documents
    assert not _pieces_look_like_documents(text, dashes)

    backend = FakeBoundaries(["====Відділення  Лабораторія===="], chooses="A")  # the dashes: commonest
    find_boundaries(output, record, root, backend)

    line = json.loads((output / "boundaries.jsonl").read_text().splitlines()[0])
    assert line["found_by"] == "windows"  # refused, and the file was walked instead


def test_a_file_with_no_fences_of_its_own_is_walked_in_windows(tmp_path):
    from epicrisis.boundaries import find_boundaries

    root, output = one_text_archive(tmp_path)
    record = next(read_records(output / "inventory.jsonl"))

    backend = FakeBoundaries(["ВИПИСКА З ІСТОРІЇ ХВОРОБИ"], chooses="none")
    find_boundaries(output, record, root, backend)

    assert backend.calls  # it was read, window by window
    assert json.loads((output / "boundaries.jsonl").read_text().splitlines()[0])["found_by"] == "windows"


def test_a_window_that_will_not_answer_is_halved_rather_than_lost(tmp_path):
    """A window with no answer is not a gap in the markup: it is two documents silently joined."""
    from epicrisis.boundaries import SMALLEST_WINDOW_CHARS, find_boundaries
    from epicrisis.classify.backend import BackendError
    from epicrisis.sources import Source

    # Long enough that a window can be halved twice before the floor under halving is reached.
    root = tmp_path / "archive"
    root.mkdir()
    first = A_VISIT + "рядок опису стану\n" * 150
    (root / "history.txt").write_text(first + ANOTHER + "рядок опису стану\n" * 150, encoding="utf-8")
    output = tmp_path / "out"
    output.mkdir()
    write_inventory(root, output / "inventory.jsonl")
    record = next(read_records(output / "inventory.jsonl"))

    class Sulky(FakeBoundaries):
        def read(self, text, workdir):
            self.calls.append(text)
            if len(text) > 4_000:  # answers only once it has been cut down
                raise BackendError("timeout")
            return {"documents": [{"first_line": "ВИПИСКА З ІСТОРІЇ ХВОРОБИ"}] if "ВИПИСКА" in text else []}

    backend = Sulky()
    find_boundaries(output, record, root, backend)

    assert len(backend.calls) > 1  # the window was cut down until it was answered
    line = json.loads((output / "boundaries.jsonl").read_text().splitlines()[0])
    assert line["windows_halved"] >= 1
    assert line["cuts"] == [0, len(first)]  # and the boundary inside it was still found

    class Mute(FakeBoundaries):
        def read(self, text, workdir):
            raise BackendError("timeout")

    (output / "boundaries.jsonl").unlink()
    try:
        find_boundaries(output, record, root, Mute())
    except BackendError:
        pass  # halving has a floor: a window that will not answer at all is said, not swallowed
    else:
        raise AssertionError("a window nobody could answer must not pass as an answer")
    assert SMALLEST_WINDOW_CHARS > 0


def one_text_archive(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "archive"
    root.mkdir()
    (root / "history.txt").write_text(A_VISIT + ANOTHER, encoding="utf-8")
    output = tmp_path / "out"
    output.mkdir()
    write_inventory(root, output / "inventory.jsonl")
    return root, output


def test_the_marks_decide_the_pages_and_are_read_once(tmp_path):
    """The cuts go into the record, so every reader of the inventory sees one file."""
    from epicrisis.sources import Source

    root, output = one_text_archive(tmp_path)
    source = Source(id="an-id", name="archive", path=str(root), added_at="2026-10-02T00:00:00+00:00", owner="A Person")
    data_dir = tmp_path
    (data_dir / "sources").mkdir(exist_ok=True)
    (data_dir / "sources" / "an-id").symlink_to(output)
    backend = FakeBoundaries(["ВИПИСКА З ІСТОРІЇ ХВОРОБИ"])

    assert read_boundaries(data_dir, source, backend) == 1

    record = next(read_records(output / "inventory.jsonl"))
    assert record["text"]["cuts"] == [0, len(A_VISIT)]
    assert record["text"]["pages"] == 2
    assert record["text"]["of_document"] == [0, 1]
    assert len(backend.calls) == 1

    # Asked again, it is not asked of a model again: the answer is kept with its own file.
    again = FakeBoundaries(["ВИПИСКА З ІСТОРІЇ ХВОРОБИ"])
    assert read_boundaries(data_dir, source, again) == 0 and again.calls == []

    # And a walk of the folder that wipes the cuts puts them back without a model.
    write_inventory(root, output / "inventory.jsonl")
    assert read_boundaries(data_dir, source, again) == 1 and again.calls == []
    assert next(read_records(output / "inventory.jsonl"))["text"]["cuts"] == [0, len(A_VISIT)]


def test_the_pages_of_a_marked_file_carry_the_document_they_belong_to(tmp_path):
    from epicrisis.sources import Source

    root, output = one_text_archive(tmp_path)
    source = Source(id="an-id", name="archive", path=str(root), added_at="2026-10-02T00:00:00+00:00", owner="A Person")
    (tmp_path / "sources").mkdir(exist_ok=True)
    (tmp_path / "sources" / "an-id").symlink_to(output)
    read_boundaries(tmp_path, source, FakeBoundaries(["ВИПИСКА З ІСТОРІЇ ХВОРОБИ"]))
    record = next(read_records(output / "inventory.jsonl"))

    refs = page_refs(record)

    assert [(ref.page, ref.part, ref.document) for ref in refs] == [(1, "text", 0), (2, "text", 1)]

    # And the grouping follows the marks, asking the reader of a page nothing about where it
    # stands: both pages here would be a "continuation" of nothing, and both are their own.
    pages = [{"file_sha256": "a", "page": ref.page, "part": "text", "of_document": ref.document,
              "page_role": "continuation", "date_on_page": None} for ref in refs]  # fmt: skip
    assert [[one["page"] for one in document] for document in group_documents(pages)] == [[1], [2]]


def test_boundaries_are_kept_with_what_was_asked_and_how_much_was_thrown_away(tmp_path):
    from epicrisis.sources import Source

    root, output = one_text_archive(tmp_path)
    source = Source(id="an-id", name="archive", path=str(root), added_at="2026-10-02T00:00:00+00:00", owner="A Person")
    (tmp_path / "sources").mkdir(exist_ok=True)
    (tmp_path / "sources" / "an-id").symlink_to(output)
    backend = FakeBoundaries(["ВИПИСКА З ІСТОРІЇ ХВОРОБИ"])
    backend.read = lambda text, workdir: {"documents": [
        {"first_line": "ВИПИСКА З ІСТОРІЇ ХВОРОБИ"},
        {"first_line": "a line nobody wrote"},
    ]}  # fmt: skip

    read_boundaries(tmp_path, source, backend)

    line = json.loads((output / "boundaries.jsonl").read_text().splitlines()[0])
    assert line["documents"] == 2 and line["lines_not_found"] == 1
    assert line["prompt_version"] == PROMPT_VERSION
    assert line["provenance"]["model"] == "fake-haiku"


def an_inventory_of_one_file(folder: Path) -> Path:
    """One inventory line, written by hand, so the write under test is the only one measured."""
    inventory = folder / "inventory.jsonl"
    inventory.write_text(json.dumps({"sha256": "abc", "path": "a-file.txt"}, ensure_ascii=False) + "\n",
                         encoding="utf-8")  # fmt: skip
    return inventory


def test_the_inventory_the_cuts_go_into_is_handed_back_to_the_person_whose_archive_it_is(tmp_path):
    """This step is started from the dashboard, and on this machine the dashboard runs as root.

    The cuts were written into the inventory by hand — a rename of this module's own, past the one
    place that writes a file of state here — so nothing gave the file back to the owner of the
    archive. Started from the dashboard, the table of every file in the archive became root's and
    the next command that person ran could not read it. That is the failure runs.belongs_to_the_folder
    was written for, and the only honest way to show it without being root is to show that it is
    asked: a test cannot pretend to own a file it does not own.
    """
    from epicrisis import runs
    from epicrisis.boundaries import put_the_cuts_in_the_inventory

    inventory = an_inventory_of_one_file(tmp_path)
    handed_back: list[Path] = []
    was = runs.belongs_to_the_folder
    runs.belongs_to_the_folder = lambda path: handed_back.append(Path(path))
    try:
        put_the_cuts_in_the_inventory(inventory, "abc", [0, 900], [("a page", 0), ("another", 1)])
    finally:
        runs.belongs_to_the_folder = was

    assert handed_back == [inventory], "the inventory was written without being handed back to its owner"


def test_the_cuts_are_written_under_a_name_no_other_writer_of_the_inventory_shares(tmp_path):
    """A temporary name is one per process, because os.replace is atomic and two writers are not.

    This one was fixed — inventory.boundaries.partial, the same name in every process — so a
    second writer of the inventory opened the file the first was still filling, and what the
    winner renamed into place was the loser's half. Here the fixed name holds somebody else's
    half-written bytes; after this write they are still there, untouched, because this writer has
    no reason to know that name.
    """
    from epicrisis.boundaries import put_the_cuts_in_the_inventory

    inventory = an_inventory_of_one_file(tmp_path)
    halfway = inventory.with_suffix(".boundaries.partial")
    halfway.write_text('{"sha256": "another writer, halfway thro', encoding="utf-8")

    put_the_cuts_in_the_inventory(inventory, "abc", [0, 900], [("a page", 0), ("another", 1)])

    assert halfway.read_text(encoding="utf-8") == '{"sha256": "another writer, halfway thro'
    assert json.loads(inventory.read_text(encoding="utf-8"))["text"]["cuts"] == [0, 900]
    assert not list(tmp_path.glob("*.tmp")), "a temporary file was left behind"
