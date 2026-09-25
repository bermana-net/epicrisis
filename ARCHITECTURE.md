# Where things live

One decision, one place. This file says which place — so that a thing added next month lands
where the same kind of thing already is, instead of beside the code that happened to need it
first. That is how the choice of model ended up written into ten files, and how an icon reached
one page out of twelve.

Read the two tables before adding anything.

## The modules

| Module | The one thing it decides |
|---|---|
| `settings.py` | What this instance allows: `data/settings.json`, one reader and one writer per setting. **Nothing else reads that file.** |
| `engines.py` | How a model is reached — Claude Code on this machine or the Anthropic API with a key — and which model does which pass. Hands out something that can answer; callers never learn how. |
| `models.py` | The passes (first reading, expert reading, second opinion) and the models this program knows how to name. |
| `units.py` | What counts as one unit written differently, what converts into what, the unit a printed range names, and the scale a printed range says a form used. |
| `sources.py` | What an archive is: the registry, the ids, which one is showing, where its derived files go. |
| `layout.py` | What the files beside an archive are called. Nothing decides anything there; everyone imports the name instead of writing it out. |
| `runs.py` | One run of a step at a time, and a written file that stays the archive owner's own. |
| `records.py` | The ledgers this program appends to, and the one kind of timestamp. |
| `parallel.py` | How many things are done at once, and the lock around shared state. |
| `printed_values.py` | The folding of printed text — case, accents, alphabets — that every match in the program is made on. |
| `values.py` | What counts as the result of a form, rather than something printed beside it — for the queries, the checks and the charts alike. |
| `reference.py` | Reading a printed reference range. One reader for the whole program. |
| `dates.py`, `document_dates.py` | Reading a printed date, and settling which date a document carries. |
| `indicators.py` | Which printed spellings are one test, and the corrections a person made to that. |
| `corrections.py` | What a person changed by hand, kept apart from what a model wrote and laid over it, and which printed fields they may change at all. |
| `validate.py` | The checks that need no model, and what goes to review. |
| `rules/` | What a rule is, which kinds of check exist, and the rules that ship. A rule is a file; a kind is code. How to write one, including one that needs a model: `rules/README.md`. |
| `suspects.py` | Lines that look misread, ranked. Reads the index only. |
| `query.py` | Every question the index is asked, and the caps on how much comes back — asked-for numbers pass through `within_limit`. |
| `series.py` | Charts: geometry from printed numbers. Draws, never reads meaning. |
| `mcp_server.py` | The read-only tools an assistant reaches, the lock in front of them, and what a refusal says. |
| `mcp_lock.py`, `mcp_access.py` | The six-digit code and its passes; the log of who called. |
| `ask.py` | The page that asks a model questions: conversations, prompts, the tool loop. |
| `consent.py` | Whether this instance may send pages to a model, and to which destination it agreed. |
| `update.py` | One command that runs every step in order and stops where it should. |
| `datesearch.py` | Looking inside a document for a date it printed nowhere obvious. |
| `material_reading.py` | Reading what a table was measured in, where the form did not say. |
| `indicator_proposals.py`, `indicator_check.py`, `indicator_web_check.py` | Grouping printed names into one test, checking those groups, and settling a name against the web. |
| `recheck.py` | Reading a document a second time with another model and showing where the two differ. Changes nothing. |
| `classify/`, `extract/`, `index/`, `inventory/` | One step of the pipeline each, and nothing about how a model is reached. |
| `web/app.py` | The pages: routes and the context each page needs. |
| `web/templates/_page.html` | The shell every page is drawn in: head, body, the class on the page. |
| `cli.py` | The command line: options, and printing numbers. Decides nothing else. |
| `demo.py` | Three archives of people who do not exist, built without calling a model. |
| `tools/nothing-of-yours.py` | Whether anything of a real archive is in this repository. Runs before every push. |

## Where a new thing goes

| Adding | Goes in |
|---|---|
| A setting a person can change | `settings.py` — a reader and a writer, default in the reader. Then the switch on the settings page. |
| Another way to reach a model | `engines.py` — a new call class and a line in `ENGINES`. Nothing else changes. |
| A model name | `models.py`. |
| A unit, two spellings that are one unit, or a scale a form printed at | `units.py`. |
| A check that sends a line to review | A rule file in `epicrisis/rules/shipped/`, naming a kind that exists. Never a new branch in a step. `validate.py` still holds the checks that have not moved yet. |
| A kind of check no rule can express yet | `rules/kinds.py` — one entry saying what it looks at, which step runs it, and whether it marks or places. The doing goes in the module that owns the decision, and the kind names it. |
| A rule that needs to ask a model | `rules/README.md` says what holds: through `engines.py`, at a costly step, prompt as a named field with a version of its own, consent checked, and still only marks or places. |
| A subject a kind needs and none of the four gives | `rules/subjects.py`. It holds what was printed and never the means to change anything. |
| A page | A template extending `_page.html`, a route in `web/app.py`. Never a second `<head>`. |
| A column or a question of the index | `query.py`, and the index schema in `index/build.py`. |
| A tool an assistant can call | `mcp_server.py`, read-only, with `archive_of` on the answer. |
| A step of the pipeline | Its own package under `epicrisis/`, with the model reached through `engines.py` and the run through `runs.py`. |
| A file written beside an archive | Its name in `layout.py`, written through `runs.put_in_place`. |

## Two rules that hold everywhere

**The program stores and shows.** Nothing added here may interpret a value, decide what is
normal, average, score or advise. A check may mark a line for a person to look at; that is the
furthest it goes (MDCG 2019-11).

**Nothing of a real archive leaves this repository.** No value, no name, no institution — not in
code, not in tests, not in commit messages. `tools/nothing-of-yours.py` refuses the push when it
finds any, and it reads the live data directory to know what to look for.
