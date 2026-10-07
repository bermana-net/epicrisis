"""The first command a stranger runs, and the folder it is pointed at.

`epicrisis demo --into /var/tmp/demo` drew one invented person's archive, wrote the data directory
beside it, and then put the folder on the list of archives — where the list refused it, because
/var belongs to the server. What came out was a Rich traceback of sixty-nine lines naming cli.py
and the inside of the registry, over forty-three files and 6.6 MB already on disk. The seventh
entry of the constitution wants which folder will not do, what is safe, and what puts it right.

Nothing here builds a demo: every test is about the moment before the first byte.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from epicrisis import sources
from epicrisis.cli import app
from epicrisis.sources import SourceError


@pytest.fixture
def a_folder_of_the_server(tmp_path, monkeypatch) -> Path:
    """A folder the registry refuses, which no test may make by writing in /var or /usr.

    The question is asked of `sources.SYSTEM_FOLDERS` at the moment it is asked, so a folder of
    this test's own is put on that list rather than a real one of the server's. A test that
    proves nothing was written by looking at /usr/share would have had to write there to fail.
    """
    monkeypatch.setattr(sources, "SYSTEM_FOLDERS", sources.SYSTEM_FOLDERS | {str(tmp_path)})
    return tmp_path / "demo"


def test_the_demo_refuses_a_folder_of_the_server_before_it_writes_anything(a_folder_of_the_server):
    """The refusal, and the empty disk behind it."""
    from epicrisis.demo import build

    with pytest.raises(SourceError) as refused:
        build(a_folder_of_the_server)

    said = str(refused.value)
    assert str(a_folder_of_the_server) in said, "the folder that will not do is not named"
    assert str(a_folder_of_the_server.parent) in said, "the reason — the folder it is inside — is not named"
    assert "Nothing has been written" in said
    assert not a_folder_of_the_server.exists(), "the folder was made before the folder was looked at"
    assert not list(a_folder_of_the_server.parent.iterdir()), "something of a demo is on the disk"


def test_the_demo_names_a_folder_that_would_do_and_the_line_that_does_it(a_folder_of_the_server, monkeypatch):
    """A refusal with no way out is a defect, and the way out is a line that can be typed.

    Typed as a shell reads it, which is why the line is taken apart with shlex here: the folder
    offered carries the name of the one that was asked for, and "my demo" breaks a line in two.
    """
    import shlex

    from epicrisis.demo import why_it_cannot_be_built_here

    said = why_it_cannot_be_built_here(a_folder_of_the_server)

    assert "demo --into" in said, "the command to type is not in the refusal"
    offered = Path(shlex.split(said.rsplit("--into ", 1)[1])[0])
    assert offered.is_absolute()
    assert not sources.belongs_to_the_server(offered), f"{offered} would be refused in the same words"

    monkeypatch.setattr(Path, "home", staticmethod(lambda: a_folder_of_the_server.parent.parent))
    with_a_space = a_folder_of_the_server.with_name("my demo")
    line = why_it_cannot_be_built_here(with_a_space).rsplit("--into ", 1)[1]
    assert shlex.split(line) == [str(Path.home() / "my demo")], f"not one word of a shell: {line}"


def test_the_folder_offered_is_never_one_the_server_would_refuse(monkeypatch):
    """Served as root, Path.home() is /root — which is one of the folders being refused.

    The folder picker did this once: it told somebody to add /root as an archive in the same
    sentence that refused to show it to them. A refusal naming a folder that is itself refused is
    worse than a refusal naming none.
    """
    from epicrisis.demo import a_folder_that_would_do

    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/root")))
    assert a_folder_that_would_do("demo") == Path("/tmp/demo")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/home/somebody")))
    assert a_folder_that_would_do("demo") == Path("/home/somebody/demo")


def test_the_demo_refuses_a_path_that_is_a_file_and_leaves_the_file_alone(tmp_path):
    """The other dead end: --into pointing at a file, where not even the data directory can be made.

    It left no litter, only a NotADirectoryError with the path printed twice and nothing about
    what to do. Whatever is in that file is somebody's, and it is still there afterwards.
    """
    from epicrisis.demo import build

    a_file = tmp_path / "already-here"
    a_file.write_text("not a folder", encoding="utf-8")

    with pytest.raises(SourceError) as refused:
        build(a_file)

    assert str(a_file) in str(refused.value) and "folder" in str(refused.value)
    assert a_file.read_text(encoding="utf-8") == "not a folder"
    assert list(tmp_path.iterdir()) == [a_file]


def test_the_command_says_the_sentence_and_no_traceback(a_folder_of_the_server):
    """What the terminal shows: the sentence, and the code a script reads. Not a stack."""
    result = CliRunner().invoke(app, ["demo", "--into", str(a_folder_of_the_server)])

    assert result.exit_code == 2, result.output
    assert "Traceback" not in result.output and "SourceError" not in result.output
    # The first thing the terminal shows is the folder, and the whole of what it shows is the
    # sentence about it: a refusal that begins with a frame has already lost the person reading it.
    assert result.output.strip().startswith(str(a_folder_of_the_server))
    assert str(a_folder_of_the_server.parent) in result.output
    assert not a_folder_of_the_server.exists()
