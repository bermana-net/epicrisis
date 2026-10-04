# Where things live

One decision, one place. This file says which place — so that a thing added next month lands
where the same kind of thing already is, instead of beside the code that happened to need it
first. That is how the choice of model ended up written into ten files, and how an icon reached
one page out of twelve.

Read the two tables before adding anything.

A row of this file is a claim, and a claim can go stale while the code moves under it. Where one
has, the row says so in its own words rather than describing the program somebody meant to
write: a row that reads as an aspiration is worse than no row, because the next person trusts it.
Eleven modules had no row at all when this was last audited, and four rows named one owner for a
decision that is taken in two.

## The modules

| Module | The one thing it decides |
|---|---|
| `settings.py` | What this instance allows: `data/settings.json`, one reader and one writer per setting, under one lock, one write per change. **Nothing else reads that file** for what is in it. `tools/chart-snapshot.py` copies it as bytes, to freeze one set of answers across the two trees it measures, and reads nothing out of it. |
| `engines.py` | How a model is reached — Claude Code on this machine or the Anthropic API with a key — and which model does which pass. Hands out something that can answer; callers never learn how. |
| `models.py` | The passes (first reading, expert reading, second opinion) and the models this program knows how to name. |
| `units.py` | What counts as one unit written differently, what converts into what, the unit a printed range names, and the scale a printed range says a form used. |
| `sources.py` | What an archive is: the registry, the ids, which one is showing, where its derived files go. |
| `layout.py` | What the files beside an archive are called. Nothing decides anything there; everyone imports the name instead of writing it out. The one name it does **not** hold is an archive's index file: that shape is `index/build.index_path`, and `web/app.py` asks it rather than spelling it out. |
| `state.py` | What is said when one of this program's own files is there and will not parse: which file, what has not been lost, and the one act that mends it. One sentence, built once, so the terminal and the page say the same words. |
| `invocation.py` | How a person on this machine types a command of this program, worked out once from where the script actually is. Every page and message that tells somebody what to run asks here. |
| `backup.py` | Which part of an instance nothing can make again, and copying exactly that out. Decides nothing about what the files mean; `layout.py` says which they are. |
| `runs.py` | One run of a step at a time, and a written file that stays the archive owner's own. |
| `records.py` | The ledgers this program appends to, and the one kind of timestamp. |
| `parallel.py` | How many things are done at once, and the lock around shared state. |
| `doc_types.py` | What kinds of document there are: the name a model returns and the index stores, and the words a page prints for it. Templates ask it through the `in_words` filter. |
| `everyday_words.py` | Which word people say for a test a laboratory prints another name for. Small, explicit, shipped, no model — and only ever reached where a question found nothing by name. |
| `printed_values.py` | The folding of printed text — case, accents, alphabets — that every match in the program is made on, and the one answer to what a name somebody typed may be called where only Latin letters can be carried: a file, an id, a URL. |
| `values.py` | What counts as the result of a form, rather than something printed beside it — for the queries, the checks and the charts alike. The SQL sites take the fragment, the Python sites take the question; `series.html` and `index/build.py` still write the word `"result"` out, which is the last of the twelve. |
| **Copies** — no one module, and it should be one | **Which documents are the same result** is the `possible_copy` rule, decided in `validate.possible_copies`; `index/build._copy_groups` only joins what it found. **Which copy is the one to show** is decided in three: a ranking in `index/build.py`, the press in `query.choose_primary_copy`, and the person's own answer in `corrections.set_primary_copy` — and one press writes it twice, which `query.choose_primary_copy` records as a defect it already caused. `review.html` then states the ranking a fourth time, in prose. `primary_copy = 1` filters nearly every count in the program, so this is the largest decision in the program with no row of its own. See the card. |
| `reference.py` | Reading a printed reference range. One reader for the whole program — including a line that printed **one band per unit**, "47 – 72 % 2,000 – 5,500*10⁹/л", which it reads as the two ranges it is: `a_band_for_each_unit` says what shape is accepted and why it is unambiguous, and `parse`, `printed_ends` and `outside` take the unit of the value in hand to say which band stands beside it. Which unit a band names is still `units.py`'s answer and is asked of it. |
| `dates.py`, `document_dates.py` | Reading a printed date, and settling which date a document carries — including **how precisely it is known**, which travels with the date and is never worked out again from the label it was formatted into. |
| `quotations.py` | A value a document quotes from another study, and the date that value really has: what makes a quotation, and the two shapes a date in a value's own line may take. It reads named months through `dates.py` and has numeric shapes of its own, because a range is two numbers over a dash and must never be read as a date. |
| `eyes.py` | One line of an eye examination, and which measurement each number in it is. The one place in this program that must **not** use `printed_values.fold`, and says why: the fold drops the soft sign, and that is the only letter telling «ось» from «ос». |
| `about_the_person.py` | The few things a form prints about the person rather than about the day: what has one answer for a person, and where two documents disagree about one. Settles nothing. |
| `indicators.py` | Which printed spellings are one test, and the corrections a person made to that. |
| `people.py` | Which printed spellings are one doctor or one institution — joined, offered or refused, and only ever settled by hand. One file per archive, inside it, under one lock. |
| `people_proposals.py` | Which printed names a model thinks are one doctor or one place. Nothing it writes is ever applied: there is no `sure` field to be tempted by, and the label is the commonest spelling, counted. |
| `doctors_in_text.py` | Which doctor a document names inside its own stored text, where no field of it holds one. No model, no file, nothing written and nothing filled in: it reads the index's own `page_texts`, requires a name to prove it is a name — initials, a patronymic behind two names, or an honorific in front — and hands the page the printed line beside each, which is what makes a wrong reading visible. Every join is still the press in `people.py`. |
| `conversing.py` | A question answered through a conversation with this archive's tools, over the API: the loop Claude Code has built in. |
| `judgements.py` | What a person said about a finding: that it was real, or that it was noise. Appended, never rewritten. |
| `corrections.py` | What a person changed by hand, kept apart from what a model wrote and laid over it, and which printed fields they may change at all. |
| `validate.py` | The checks that need no model, and what goes to review. |
| `rules/` | What a rule is, which kinds of check exist, and the rules that ship. A rule is a file; a kind is code. How to write one, including one that needs a model: `rules/README.md`. A rule's thresholds are its own file's `[settings]`, and `rules/kinds.py` carries the same numbers again as the defaults a rule with none falls back to — two statements of one threshold, held together by nothing but care. |
| `rules/tally.py` | How often each rule fires on one archive, asked live rather than stored, so that the count beside a switch and the page behind it cannot drift. |
| `suspects.py` | Lines that look misread, ranked. Reads the index only — **except** `provider_looks_like_a_person`, which lives here and is asked by `index/build.py` and `extract/run.py` as well. That one is a decision about whether a printed field names a person, and it does not belong to a step that ranks; see the card for it.<br><br>It had a third caller — the rule `institution_looks_like_a_name`, asking it of the provider column, without the title the other two give. That column is empty on exactly the documents the question is about, because `index/build.institution_and_doctor` has already moved the name into the doctor's, so the rule found 0 on every archive and could never find one. The rule now reads what the index wrote down (`documents.person_printed_as_the_institution`) and asks nothing itself: the predicate is asked where the answer is acted on, and both of the two places left give it the title. |
| `query.py` | Every question the index is asked, and the caps on how much comes back — asked-for numbers pass through `within_limit`. There are **two** caps and which a caller gets is decided here: `MAX_LIMIT` for an answer a model reads, and `MAX_SERIES` for a page its own owner reads, which prints how many there are beside what it draws. A page asks through a door that holds the larger one — `whole_history`, `every_indicator` — and never by naming a number at the call site. The eight `le=200` bounds in `mcp_server.py` are the tool cap stated a second time; see the card. |
| `series.py` | Charts: geometry from printed numbers. Draws, never reads meaning. |
| `mcp_server.py` | The read-only tools an assistant reaches, the lock in front of them, and what a refusal says. |
| `mcp_lock.py`, `mcp_access.py` | The six-digit code and its passes; the log of who called. |
| `journal.py` | What went wrong, and the few decisions nothing else records — a name settled by hand, an archive switched, a setting changed. Types, lines, counts and this program's own words — never a message, a name or a question, so the whole file can be shown to anybody. |
| `ask.py` | The page that asks a model questions: conversations, prompts, the tool loop. |
| `consent.py` | Whether this instance may send pages to a model, and to which destination it agreed. |
| `update.py` | One command that runs every step in order and stops where it should. |
| `datesearch.py` | Looking inside a document for a date it printed nowhere obvious. |
| `material_reading.py` | Reading what a table was measured in, where the form did not say. |
| `indicator_proposals.py`, `indicator_check.py`, `indicator_web_check.py` | Grouping printed names into one test, checking those groups, and settling a name against the web. |
| `recheck.py` | Reading a document a second time with another model and showing where the two differ. Changes nothing. |
| `readers/` | One module for each kind of file an archive holds, and one place saying which reader serves which kind. A reader answers four questions and no more — what is true of this file, what its pages are, a page as words, a page as a picture — and the steps ask them. A format added is a module here and a line in `READERS`, never a branch in a step. |
| `boundaries.py` | Where one document ends and the next begins inside a file that is nothing but text. A text file has no pages of its own, so the cuts are read before it is cut, and a line this program cannot find verbatim in the file is not a cut. |
| `classify/`, `extract/`, `index/`, `inventory/` | One step of the pipeline each, and nothing about how a model is reached. `classify/backend.py` is the exception that should not be: `SMALL_MODEL` and `STRONG_MODEL` live there and nine modules take them as a constructor default, which is `models.py`'s answer written a second time. Ask `engines.py` for a reader; see the card. |
| `web/app.py` | The routes, and nothing else: the address, the form it takes, the template it draws and where a press is sent next. What a page shows, and what one press of it did, are decided beside the page — `web/timeline.py`, `web/who.py`, `web/indicators_page.py`, `web/documents.py` (the documents, the card, one scan and the page of things to check), `web/settings_page.py`, `web/looks_misread.py` (the lines a rule of the `suspects` step says look misread, counted for the one line on the page of findings and listed on their own page), `web/the_list_of_archives.py` (the six presses on the archive status page), `web/browse.py`, `web/jobs.py`, `web/building.py` — each taking which archive as an argument with no default and knowing nothing of `request`, `templates` or FastAPI. A route that decides something is a decision only a fetched address can ask about, which is why every count that disagreed with another count on the same page was found by eye. |
| `web/templates/_page.html` | The shell every page is drawn in: head, body, the class on the page. |
| `web/markdown.py` | How a model's answer is rendered: tables as tables, and no HTML written in the text ever reaches the page. |
| `cli.py` | The command line: options, and printing numbers. Decides nothing else. |
| `demo.py` | Three archives of people who do not exist, built without calling a model. |
| `tools/nothing-of-yours.py` | Whether anything of a real archive is in this repository. Runs before every push. |
| `tools/findings-snapshot.py`, `tools/reader-shapes.py`, `tools/chart-snapshot.py` | The three rulers a change is measured against: every finding of every check, every printed shape, every chart. Each says which archive and which build of it it read, and none of them writes inside this repository. A ruler kept outside the tree is a ruler nobody can diff against an older commit — that is where the chart one was, and it cost a round of findings arguing about one chart.<br><br>**Two things the row did not say, and both change how they are used.** `findings-snapshot.py` writes *inside the archive*: it re-runs the checks and rebuilds the index, which is `validation.json` and `index-<id>.sqlite` written over. Only `reader-shapes.py` and `chart-snapshot.py` are safe on an archive that must not be touched. A ruler that disagrees with itself between two runs would be worse than no ruler, so this was looked for and **not found**: an audit reported it, and the attempt to reproduce it ran the chart ruler over the three live archives three times with no seed set and six times at fixed seeds on this commit, and four times at fixed seeds on the commit the audit was cut from. Every run on a given commit was identical byte for byte — 912 charts here, 924 there. What the audit saw is unexplained and may have been two runs over two different trees on a day when this branch moved five times. Measure, do not assume, and if a diff of two runs ever shows movement nobody made, that is the first thing to chase. |

## Where a new thing goes

| Adding | Goes in |
|---|---|
| A setting a person can change | `settings.py` — a reader and a writer, default in the reader, `@while_editing` over the writer, and its name in `SAID_IN_FULL` if the journal may say what it became as well as that it changed. Then the switch on the settings page. |
| Another way to reach a model | `engines.py` — a new call class and a line in `ENGINES`. Nothing else changes. |
| A model name | `models.py`. |
| A step that needs a model to read for it | A factory in `engines.py` beside `classifier`, `extractor`, `date_search`, `boundary_reader`, `second_reader`, and the step asks for it by name. Never `SomeBackend()` with the model left to its default: that default is a constant in `classify/backend.py`, and taking it means the person's answer on the Settings page is not asked. |
| A kind of file an archive can hold | A module in `readers/` answering the four questions, and a line in `readers.READERS`. Never a branch in the inventory and another in classify, which is where this was. |
| A unit, two spellings that are one unit, or a scale a form printed at | `units.py`. |
| A check that sends a line to review | A rule file in `epicrisis/rules/shipped/`, naming a kind that exists. Never a new branch in a step. `validate.py` still holds the checks that have not moved yet. |
| A kind of check no rule can express yet | `rules/kinds.py` — one entry saying what it looks at, which step runs it, and whether it marks or places. The doing goes in the module that owns the decision, and the kind names it. |
| A rule that needs to ask a model | `rules/README.md` says what holds: through `engines.py`, at a costly step, prompt as a named field with a version of its own, consent checked, and still only marks or places. |
| A subject a kind needs and none of the four gives | `rules/subjects.py`. It holds what was printed and never the means to change anything. |
| A page | A template extending `_page.html`, a route in `web/app.py` that is a shell, and what it shows gathered in a module beside it — the archive an argument with no default, no `request` and no FastAPI. Never a second `<head>`. |
| A kind of document, or the words a page prints for one | `doc_types.py` — the name and its wording on one line. Never a second dictionary beside the page that happened to need it: there was one, and six pages out of seven printed the name the model returned instead. |
| A column or a question of the index | `query.py`, and the index schema in `index/build.py`. A question asked for a page asks through a door that holds the page's cap, and a number is never named at the call site. |
| A count printed on a page | The same gathering that produced the list under it, cut the same way — `web/looks_misread.py` is the shape to copy: the one line on the page of findings is the full gathering asked with `limit=0`. A count from a second query, or from a `len()` of a list a cap or a `{% if %}` has already thinned, is the seventh entry of the constitution waiting to happen. Two more shapes for where one gathering will not serve: where the count and the list are two queries, the condition is written once and both ask it — `query.drawn_against_a_day`, the row of material tabs and the list of tests under it. Where what is drawn is settled in more than one place, the counting is a function of the view and whoever changed the drawing last asks it again — `web/documents.how_many_documents_to_check`, asked by `review_view` and again by `_from_the_index`. Where the cut has to stay, the page says both numbers and offers the rest in one press: `all_tests` in the timeline, `all_waiting` on the indicator page. |
| An everyday word for a test | `everyday_words.py` — one line, and only if the sentence "what people call X, a form prints as a row named Y" can be written about it. Never a symptom, an organ, a diagnosis or a verdict on a value: that would be the interpretation the third entry refuses, one plausible line at a time. |
| A tool an assistant can call | `mcp_server.py`, read-only, with `archive_of` on the answer. |
| A step of the pipeline | Its own package under `epicrisis/`, with the model reached through `engines.py` and the run through `runs.py`. |
| A way of telling a rule it was right or wrong | `judgements.py`, and the count beside the switch in `rules/tally.py`. |
| A file written beside an archive | Its name in `layout.py`, written through `runs.put_in_place`. |
| A door that needs to know whose archive it is about | The one place that already decides it, never the archive that happens to be open: an index is `query.open_index`, which gives a named archive its own file or nothing; a tool call is `showing()` in `mcp_server.py`, read **once** per call by `answering()` and carried through the pass, the index and `archive_of` together; a conversation is `ask._one_archive_or_none`, which `ask.whose_archive` asks to answer a question out of an archive and `ask._belongs` asks to show the conversation in one — the same question from the two sides, so it has one answer and one place; a page is `the_archives_of` in `web/app.py`, read **once** per request — one reading of `sources.json` and no second one — and declared by every route that is about somebody's records, which then hands it as a value to the module that gathers the page, to the index and to the presses that write. Its other half is `_the_open_archive`, which takes the archive out of the address and answers only while it is the one that is open; the presses that live beside their own page are handed that one function rather than asking the question a second time. Each of the four has been the leak once, and each of the four was a second place answering the same question differently.<br><br>**Audited, and one of the four does not hold.** `query.open_index` refuses a call that forgets the archive and there is a test that says so. The conversation door does not: `ask.list_chats` and `ask.load_chat` take the archive as `owner=None`, `_belongs` answers `True` to that, and the default therefore means *no filter at all* — `ask.ask` itself takes it. Every route passes the open archive, so nothing leaks today, and a filter written at the point of use is exactly what the first entry says is not the rule. `index_path` and `index_state` default too, to the nameless index of an instance from before archives had owners. See the cards. |

## Two rules that hold everywhere

**The program stores and shows.** Nothing added here may decide what is normal, average, score
or advise. A kind of check that `marks` may only say "look at this"; a kind that `places` may
only say what scale or unit something was printed in. There is no third one — see
`rules/kinds.py`, which says this as code rather than as a promise (MDCG 2019-11).

One door exists, and naming it is part of the rule. Where a person has turned every limit off on
their own instance, the application will compare a number with the range printed beside it on its
own form and count what fell outside. That is arithmetic on what one form printed, it is off
unless somebody switches it on, and `reference.py` is the only place in this program that does
it.

**Nothing of a real archive leaves this repository.** No value, no name, no institution — not in
code, not in tests, not in commit messages. `tools/nothing-of-yours.py` refuses the push when it
finds any, and it reads the live data directory to know what to look for.
