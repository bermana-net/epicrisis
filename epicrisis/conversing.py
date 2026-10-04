"""A question answered through a conversation with the tools of one archive, over the API.

The other engine has this loop already: Claude Code carries a question to a model, hands it the
tools, runs whichever it asks for and carries the answers back until the model has enough. This
is the same loop written here, so that an instance with a key and no Claude Code can answer a
question at all.

Three things it does not do differently, because they are the boundary and not an implementation:

- **The tools are the same tools.** The MCP server of this archive is built in this process and
  its own functions are called directly — no address, no network, no pass to unlock, because
  there is nothing here to reach from outside. One home for what a tool is and what it says
  about itself; a description written for one engine is what the other reads too.
- **The task given to the model is the same task.** `ask.system_prompt` for the mode this
  instance is set to, word for word. Where a question may be answered and what may be said about
  a value is decided in one place, and moving to another engine is not a place to redecide it.
- **The steps are the same steps.** This yields what the other engine's stream yields, so the
  page that draws a conversation never learns which engine answered it.

What is different is only what it costs: this bills the owner's key, one request per turn.
"""

import asyncio
from pathlib import Path

MOST_TURNS = 12  # tool calls before an answer is demanded: a loop is a bill as well as a wait
MOST_TOKENS = 8192
# The lock belongs to the archive reached over a network. In this process there is no address to
# reach, the pass would have nowhere to come from, and offering the tools would only invite the
# model to waste a turn on them.
NOT_IN_HERE = ("unlock", "lock_archive")


def tools_of(server) -> list[dict]:
    """The archive's own tools, in the shape the provider wants them."""
    return [
        {"name": tool.name, "description": tool.description or "", "input_schema": tool.input_schema}
        for tool in asyncio.run(server.list_tools())
        if tool.name not in NOT_IN_HERE
    ]


def _answer_of(result) -> str:
    """What a tool said, as text. Its own words: they are already written for a model to read."""
    return "\n".join(block.text for block in (result.content or []) if getattr(block, "text", None)) or "{}"


def _said(blocks: list) -> str:
    return "\n".join(block.get("text", "") for block in blocks if block.get("type") == "text").strip()


def through_the_api(data_dir: Path, prompt: str, system: str, call, server=None, pinned_to: str | None = None):
    """Ask, run whatever tools are asked for, and ask again, until there is an answer.

    Yields the events ask.py already knows: a step for every tool the model reaches for, then
    one answer, or one reason it could not.
    """
    from epicrisis.engines import carried
    from epicrisis.mcp_server import build_server

    # Built for one archive where the caller says which: a question asked of one person is
    # answered out of that person's records even if the dashboard is switched while it runs.
    server = server or build_server(Path(data_dir), pinned_to=pinned_to)
    tools = tools_of(server)
    # What this archive says about itself, in front of the task. The other engine gets this from
    # the MCP client, which reads a server's instructions and puts them before the conversation;
    # over the API nobody does, so this loop was sending the tools and the task and losing the
    # instructions — and the instructions are where the boundary lives. They are what say that an
    # empty answer is not an absence, that Protein in blood and Protein in urine are one printed
    # name and two tests that must never go in one series, that ranges and units differ between
    # laboratories and comparing across them silently is wrong, and that every answer carries
    # whose archive it came from. Without them one engine forbade all of that in words and the
    # other did not, which is the one thing this file's own docstring promises cannot happen.
    speaks = "\n\n".join(part for part in (getattr(server, "instructions", "") or "", system) if part.strip())
    messages: list[dict] = [{"role": "user", "content": prompt}]

    for _turn in range(MOST_TURNS):
        said = carried(call, {"model": call.model, "max_tokens": MOST_TOKENS, "system": speaks,
                              "messages": messages, "tools": tools})  # fmt: skip
        blocks = said.get("content") or []
        wanted = [block for block in blocks if block.get("type") == "tool_use"]
        if said.get("stop_reason") != "tool_use" or not wanted:
            text = _said(blocks)
            yield {"kind": "answer", "text": text} if text else {"kind": "error", "text": "no answer"}
            return

        results = []
        for block in wanted:
            # The step as the call goes out and `answered` as it comes back, around the one line
            # that does the work: the page records what the archive itself took, and it can only
            # be that in a conversation answered over the API if this loop says when a call
            # started and when it ended. Every step of this engine used to be yielded before any
            # of them ran, which left nothing in between to time.
            yield {"kind": "tool", "step": {"tool": block.get("name", ""), "input": block.get("input") or {}}}
            try:
                got = asyncio.run(server.call_tool(block["name"], block.get("input") or {}))
                results.append({"type": "tool_result", "tool_use_id": block["id"], "content": _answer_of(got)})
            except Exception as trouble:  # the kind only: a message can quote a document
                # A tool that failed is told to the model rather than raised at the page. It can
                # ask another way, and a conversation that ends because one call went wrong is
                # worse for the person than one that carries on with less.
                results.append({"type": "tool_result", "tool_use_id": block["id"], "is_error": True,
                                "content": f"the tool failed: {type(trouble).__name__}"})  # fmt: skip
            yield {"kind": "answered"}
        messages.append({"role": "assistant", "content": blocks})
        messages.append({"role": "user", "content": results})

    # Twelve turns and still asking for tools. Saying so is better than a thirteenth request: a
    # loop that cannot stop is a bill that cannot stop either.
    yield {"kind": "error", "text": f"the model was still asking for tools after {MOST_TURNS} turns"}


# Asking the open web
#
# One pass of this program asks the open web rather than the archive: whether a printed name is
# a real test, and what else laboratories call it. The other engine reaches the web through
# Claude Code's own search; here the provider runs the search on its own side, so there is no
# search engine of ours and no second key.
#
# The loop is the same loop with two differences. The search is the provider's tool and runs
# where we cannot see it, so nothing of ours executes for it. And the answer is not free text:
# it comes back through a tool of ours whose input is the schema, which is how this program asks
# for a shape everywhere else.

SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 8}
ANSWER = "answer"


def with_the_web(call, system: str, schema: dict, request: str) -> dict:
    """Let the model search, and take its answer in the shape asked for."""
    from epicrisis.classify.backend import BackendError
    from epicrisis.engines import carried

    tools = [SEARCH_TOOL, {"name": ANSWER, "description": "The answer, in the shape given here.",
                           "input_schema": schema}]  # fmt: skip
    messages: list[dict] = [{"role": "user", "content": request}]
    for _turn in range(MOST_TURNS):
        said = carried(call, {"model": call.model, "max_tokens": MOST_TOKENS, "system": system,
                              "messages": messages, "tools": tools})  # fmt: skip
        blocks = said.get("content") or []
        for block in blocks:
            if block.get("type") == "tool_use" and block.get("name") == ANSWER:
                if isinstance(block.get("input"), dict):
                    return block["input"]
                raise BackendError("no valid structured output")
        if said.get("stop_reason") == "max_tokens":
            raise BackendError("the answer was cut off before it was complete")
        # It searched and said something in words. The searches are the provider's own and come
        # back inside the same turn, so there is nothing here to run: it is asked again, for the
        # shape, with what it has already found still in front of it.
        messages.append({"role": "assistant", "content": blocks})
        messages.append({"role": "user", "content": f"Now give the answer through the {ANSWER} tool."})
    raise BackendError(f"no answer in the shape asked for after {MOST_TURNS} turns")
