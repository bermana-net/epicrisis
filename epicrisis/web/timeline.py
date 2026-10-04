"""The timeline page: everything `/` draws, gathered for one archive and for nobody else.

What the page shows is decided here and the route only renders it. The route used to decide it
too — a hundred and sixty lines of three views, two cuts by a name, a year, a type, a material
and a page of a list, all inside a handler — and the price was not the length. Nothing could ask
this page a question without going over HTTP, so every test of what it counts had to fetch an
address and read the answer out of the HTML, which is why the counts that disagreed with each
other were all found by eye.

It gathers and counts what the index already holds. It never rates, flags or summarises anything
about health.
"""

from contextlib import closing
from pathlib import Path

from epicrisis import everyday_words
from epicrisis import indicators as indicator_store
from epicrisis import people
from epicrisis import query as query_index
from epicrisis.printed_values import fold
from epicrisis.query import IndexMissing, open_index

VIEWS = ("feed", "lanes", "indicators")
PAGE, FEW_TESTS = 120, 40

# The order the material tabs stand in, and the words on them. Blood leads because most of a
# person's results are blood. What the form did not say comes last and stays its own answer: an
# unmarked value is probably blood, and probably is not something this archive says out loud.
MATERIAL_ORDER = ("blood", "urine", "stool", "semen", "swab", "csf", "saliva", "sputum",
                  # Last, and not materials: the two reasons a value has none. See query.MATERIAL_KEY.
                  "not_a_sample", "unknown")  # fmt: skip
# "Not said" was said of both of these, and they are not the same thing at all: one is an answer
# about a measurement made on a person, the other is a lab value whose label is missing and which
# somebody can still supply.
MATERIAL_LABELS = {"not_a_sample": "Not a sample", "unknown": "Material unknown"}


def material_tabs(counted: dict[str, int]) -> list[dict]:
    """One tab per material there is anything to show for, in that order, with its count."""
    return [
        {"key": key, "label": MATERIAL_LABELS.get(key, key), "count": counted[key]}
        for key in (*MATERIAL_ORDER, *sorted(set(counted) - set(MATERIAL_ORDER)))
        if key in counted
    ]  # fmt: skip


def timeline_view(data_dir: Path, the_archive: str | None, *, view: str = "feed",
                  year: int | None = None, doc_type: str = "", material: str = "", skip: int = 0,
                  undated: bool = False, all_tests: bool = False, paperwork: bool = False,
                  test: str = "", provider: str = "", doctor: str = "", cut: str = "") -> dict:
    """The archive by its own dates. Three views of the same documents, and two cuts of them.

    Which archive comes in as a value with no default of its own, as every door into an archive
    does: a call that forgot it would answer about whoever happened to be open, and this page is
    where that went wrong once already. The rest is what the address asked for, and an address
    that asked for nothing means the defaults written here.
    """
    context = {"current": "timeline", "view": view if view in VIEWS else "feed", "year": year,
               "doc_type": doc_type, "material": material, "query": "", "skip": max(0, skip),
               "undated": undated, "all_tests": all_tests, "paperwork": paperwork, "test": test,
               # Whose work to show: an institution, or the person who saw or signed. As
               # printed — this program does not decide that two spellings are one person.
               "provider": provider, "doctor": doctor,
               # Which of the two cuts by a name is open, and what each offers. The name in the
               # address is enough to open one: the Doctors and clinics page links to "/?doctor=…"
               # and nothing else, and the control has to stand open under such a link rather
               # than leave a person on a page that is narrowed by something they cannot see.
               "cut": cut if cut in people.KINDS else ("doctor" if doctor else "institution" if provider else ""),
               "doctors": [], "institutions": []}  # fmt: skip
    try:
        connection = open_index(data_dir, the_archive)
    except IndexMissing:
        return {**context, "missing": True}
    with closing(connection):
        since, until = (f"{year}-01-01", f"{year}-12-31") if year else (None, None)
        # The year strip of the feed view counts the documents of the type that is chosen —
        # that is what it is for. The other two views draw their own things against an axis,
        # and an axis counted over one set while the points are drawn from another puts those
        # points outside it: a type carried here from the feed view built the axis out of that
        # type's years and then drew every type on it, so eleven points of forty stood from
        # -31% to 107% of the width. Ten of them were off the left of a phone's screen, and
        # the rest stood on the wrong year, which is a page stating a date that is not true.
        showing = context["view"]
        # Asked for by the name a person chose, answered for every spelling it stands for. Only
        # the feed lists documents one at a time, so only there is a name applied: the two views
        # beside it draw their own things and would announce a narrowing nothing performs — the
        # defect the notice above the By test view was written for.
        groups = people.load(data_dir, the_archive)
        by_provider = people.names_under(groups, "institution", provider) if provider and showing == "feed" else None
        by_doctor = people.names_under(groups, "doctor", doctor) if doctor and showing == "feed" else None
        context["years"] = query_index.years(connection, doc_type or None if showing == "feed" else None,
                                             provider=by_provider, doctor=by_doctor)  # fmt: skip
        context["overview"] = query_index.overview(connection)
        # What the big line under "Timeline" counts, which has to be the set drawn under it.
        # It printed the overview whatever was in force, so a feed cut to one laboratory read
        # "41 documents · 2013-03-06 – 2025-09-21" above ten documents of 2019 to 2021, with
        # no date in the heading belonging to anything on the page. The footer said "Showing
        # 10 of 10 records under …" in small print at the other end, which is the seventh
        # entry of the constitution the other way round: the count that disagreed was the
        # large one at the top. Each view fills this with what it actually draws; the By test
        # view narrows no documents at all and keeps the archive's own, which is what the
        # notice above it already says in words.
        context["shown"] = {"documents": context["overview"]["documents"],
                            "first_date": context["overview"]["first_date"],
                            "last_date": context["overview"]["last_date"]}  # fmt: skip
        # Of the documents this page is about. Counted over the whole archive with a name
        # chosen, the line "1 document carries no date at all" promises one of somebody else's,
        # and the link under it carries the name on — unlike the year, which it drops because it
        # does not count by it.
        context["undated_count"] = query_index.count_documents(connection, undated=True, provider=by_provider,
                                                               doctor=by_doctor)  # fmt: skip
        # One entry per joined group, under the label a person chose for it, and one per name
        # nobody has joined. The row of cuts is drawn in every view, so this is asked for in
        # every view: a cut that appears in one of the three and not in the others reads as the
        # interface losing it.
        makers = query_index.who_made_them(connection, groups)
        context["doctors"] = [one for one in makers if one["what"] == "doctor"]
        context["institutions"] = [one for one in makers if one["what"] == "institution"]
        if context["view"] == "lanes":
            # One set: the filters that are in force narrow the documents, and the axis is
            # then the span of the documents that are actually drawn.
            context["lanes"] = query_index.lanes(connection, since=since, until=until,
                                                 doc_type=doc_type or None)  # fmt: skip
            # Counted off the dots themselves rather than asked for again: this view draws
            # only the documents that carry a date, so a count from the same query the feed
            # uses would promise the undated ones nothing here draws.
            dated = sorted(item["date"] for lane in context["lanes"] for item in lane["documents"])
            context["shown"] = {"documents": len(dated), "first_date": dated[0] if dated else None,
                                "last_date": dated[-1] if dated else None}  # fmt: skip
            drawn = sorted(int(item["date"][:4]) for lane in context["lanes"] for item in lane["documents"])
            if drawn:
                context["axis"] = {"first": drawn[0], "last": drawn[-1] + 1}
                # Marks inside the axis and never on its edge: with `last` one year past the
                # newest document, a mark at `last` stands at the full width and names a year
                # the page holds nothing of — and a page of a single year was labelled with the
                # year after it. Where no fifth year falls inside, the span's own first year is
                # the one mark worth printing.
                inside = [one for one in range(drawn[0], drawn[-1] + 1) if one % 5 == 0]
                context["ticks"] = inside or [drawn[0]]
        elif context["view"] == "indicators":
            # One material at a time here too: a row of dots mixing the days a test was
            # measured in blood with the days it was measured in urine reads as one history
            # of one test, and it is two.
            materials = material_tabs(query_index.materials_present(connection))
            if materials and material not in {item["key"] for item in materials}:
                material = materials[0]["key"]
            context["material"] = material
            context["materials"] = materials
            every = query_index.every_indicator(connection, material=material or None)
            if test.strip():
                # Against the label and against every printed spelling the group holds, folded
                # on both sides. A label is one language — usually English — and a person
                # looking for their own result types what their own form printed.
                wanted = fold(test)
                spellings = {item.id: item.names for item in indicator_store.load(data_dir)}

                def named_by(item, term: str) -> bool:
                    return term in fold(item["label"]) or any(term in fold(name)
                                                              for name in spellings.get(item["indicator_id"], ()))  # fmt: skip

                narrowed = [item for item in every if named_by(item, wanted)]
                # And the word people use where no printed name holds it. This box is where the
                # search page sends a person who found nothing, so a dead end here is the end of
                # the road. Only when nothing matched by name, and the page says which word it
                # answered by: see everyday_words.py.
                if not narrowed:
                    for printed_name in everyday_words.stands_for(test):
                        narrowed += [item for item in every
                                     if named_by(item, printed_name) and item not in narrowed]  # fmt: skip
                    if narrowed:
                        context["said_instead"] = test.strip()
                every = narrowed
            context["series"] = every if all_tests else every[:FEW_TESTS]
            context["series_total"] = len(every)
        else:
            context["documents"] = query_index.timeline(connection, since=since, until=until, undated=undated,
                                                        doc_type=doc_type or None, limit=PAGE, offset=context["skip"],
                                                        with_paperwork=paperwork, provider=by_provider,
                                                        doctor=by_doctor)  # fmt: skip
            context["total"] = query_index.count_documents(connection, since=since, until=until, undated=undated,
                                                           doc_type=doc_type or None, with_paperwork=paperwork,
                                                           provider=by_provider, doctor=by_doctor)  # fmt: skip
            # The heading over this list, counted and dated by the very filters the list was
            # narrowed by, so the number at the top and the one at the foot are of one set.
            context["shown"] = {"documents": context["total"],
                                **query_index.span_of_documents(connection, since=since, until=until,
                                                                undated=undated, doc_type=doc_type or None,
                                                                with_paperwork=paperwork, provider=by_provider,
                                                                doctor=by_doctor)}  # fmt: skip
            # Every tab of the row means "click and see this many", and with a year chosen it
            # did not: the counts were of the whole archive, and the link under each of them
            # carries the year on. A tab read "consultation 3" in a year that holds none, and
            # pressing it gave "Showing 0 of 0" — and then the By type view beside it, which
            # drew nothing at all. Counted here with the year in force, by the same call the
            # page's own footer counts with, so the tab and the page it leads to agree. A name
            # chosen in one of the two cuts is in force here for the same reason: every one of
            # these links carries it on, the way they carry the year.
            #
            # And "the documents that carry no date at all" the same way, which was the half of
            # this that never got carried. The links under the tabs keep `undated`, the list and
            # its footer were counted with it, and these three were not: on the archive read on
            # 4 October 2026 the undated feed held 20 documents while the Records tab over it
            # read 386 and the lab_panel tab read 217. Pressing one of them gave "Showing 0 of
            # 0" under a tab promising two hundred, which is the same defect as the year's and
            # was found by eye in the same place.
            context["type_counts"] = {
                name: query_index.count_documents(connection, since=since, until=until, doc_type=name,
                                                  undated=undated, provider=by_provider, doctor=by_doctor)  # fmt: skip
                for name in context["overview"]["types"]
            }
            # What the Records tab shows if it is pressed, so the row of tabs adds up to the
            # archive instead of leaving a person to guess what the difference was.
            context["records_count"] = query_index.count_documents(connection, since=since, until=until,
                                                                   undated=undated, with_paperwork=False,
                                                                   provider=by_provider, doctor=by_doctor)  # fmt: skip
            context["paperwork_count"] = query_index.count_documents(connection, since=since, until=until,
                                                                     undated=undated, provider=by_provider,
                                                                     doctor=by_doctor) - context["records_count"]  # fmt: skip
        return context
