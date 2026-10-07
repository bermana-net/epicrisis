"""What a run that was killed leaves on the disk, and who takes it away.

Every large file this program writes is written under a name carrying the writer's pid and then
renamed into place: one writer per name, so two of them cannot hand each other half a file. A run
that fails inside its own process clears its own name on the way out. A run that is killed — a
signal, an out-of-memory kill, the machine going down — cannot, and nothing in this program ever
looked for what those left.

It is not tidiness. An index of one of these archives is six megabytes, and the comment in
`index/build` names what that costs: a build stopped by a full disk left ninety kilobytes behind
under a pid nobody would reuse, and every attempt to free space and try again started from a disk
that was fuller than the last — "the program burying the way out a person was told to take."
"""



def test_a_half_index_left_by_a_killed_run_is_taken_away_by_the_next_one(tmp_path):
    """A run that fails inside its own process cleans up after itself; a killed one cannot.

    The name a writer writes under carries its pid, so the next attempt cannot reuse it — and
    nothing in this program ever looked for what the dead ones left. An index of one of these
    archives is six megabytes, so every build killed by a signal, an out-of-memory kill or the
    machine going down left up to that much behind, in the folder where somebody was trying to
    free space. The comment in `_build_index` names the cost: "the program burying the way out a
    person was told to take."
    """
    import os

    from epicrisis.index.build import build_index, index_path
    from epicrisis.runs import temporary_name, what_a_dead_run_left
    from epicrisis.sources import SourceRegistry

    data_dir = tmp_path / "data"
    folder = tmp_path / "an archive"
    folder.mkdir(parents=True)
    source = SourceRegistry(data_dir).add(str(folder), owner="Somebody")
    path = index_path(data_dir, source.id)
    path.parent.mkdir(parents=True, exist_ok=True)

    # What a run that was killed leaves: its own name, under a pid nobody is using. 4194303 is
    # above the usual pid_max, so it is a pid no process on this machine has.
    abandoned = path.with_name(f"{path.name}.4194303.tmp")
    abandoned.write_bytes(b"half an index" * 100)
    # And what a run that is still going has open, which must be left exactly where it is: a
    # writer that is alive is a write in progress, and this process is as alive as it gets.
    mine = temporary_name(path)
    mine.write_bytes(b"a live writer")
    assert str(os.getpid()) in mine.name

    left = {one.name for one in what_a_dead_run_left(path)}

    assert left == {abandoned.name}, "a live writer's half-written file is not litter"

    build_index(data_dir, [source])

    assert not abandoned.exists(), "the leftovers of a killed run are still there"
    assert index_path(data_dir, source.id).exists(), "and the build itself went through"
