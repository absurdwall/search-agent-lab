# Search Agent Lab

A small, hands-on Google ADK learner repository for the Search Agent Study Group.

This cumulative learner repository starts with a small onboarding foundation
and adds a Week 2 glossary tool-contract lab. It holds learner notebooks,
starter code, deterministic tests, and a tested dependency lock. It does not
own study-group planning or slides, and it does not copy Google's
shopping-agent demo.

## Weekly versions

Cloning the default `main` branch gives learners the current released week.
Earlier learner states remain available on cumulative `week-NN` branches; the
Week 1 state is `week-01`. See [docs/branching.md](docs/branching.md) for the
maintainer workflow.

## Start here

Follow [docs/setup.md](docs/setup.md) to create an isolated local environment
and pass the local environment check. The Week 2 live Notebook requires your
own Gemini API key in the untracked `.env`; never place it in Notebook source.
The recommended first path uses the Gemini API directly; Google Cloud / Vertex
is a later option.

After setup, open
[notebooks/01_glossary_qa.ipynb](notebooks/01_glossary_qa.ipynb) for the Week 2
tool-contract lab. It starts one local ADK development server on port 8000 from
inside the Notebook, exposes every fresh session in
[ADK Web](http://127.0.0.1:8000), and requires no second terminal. Keep the
Notebook kernel running while inspecting Request, Response, Event, Trace, and
Graph views because its sessions use `memory://`.

The Week 2 notebook first runs the same question through three configurations:
a baseline Agent, the glossary instruction without registered tools, and the
glossary instruction with its tools registered. Learners inspect all three runs
in ADK Web, diagnose the missing capability, inspect a vague generated tool
definition, repair the Python function interface, run the repaired Agent, and
submit two answers. The exact wording of model answers is not graded.
ADK Web is a development and teaching interface, not the final deployed
website assistant.

Week 2 also includes a deliberately narrow, single-turn local HTTP boundary
for a future website integration. See [docs/spooky-api.md](docs/spooky-api.md)
for its exact `GET /health` and `POST /v1/chat` contract, safe error mapping,
and local start command. It wraps the existing Spooky agent without exposing
ADK's session or event APIs to a browser.

After a successful checkpoint, learners can generate a deterministic,
evidence-bound agent codename and a prefilled public GitHub Issue Form. That
checkpoint is a cheerful honor-system engagement mechanism, not authentication
or formal grading; all expected evidence remains public.

## Safety and scope

- Copy .env.example to .env locally; never commit .env or credentials.
- [notebooks/00_setup_check.ipynb](notebooks/00_setup_check.ipynb) always runs
  an honest local environment check. Without a key it stops with a friendly
  waiting message; with a key it automatically attempts one real ADK run.
- [notebooks/01_glossary_qa.ipynb](notebooks/01_glossary_qa.ipynb) is the
  Week 2 cumulative lab: compare an Agent without tools with one using glossary
  tools, identify a missing tool, inspect the generated tool definition, then
  repair and test it on one Notebook-owned ADK Web server. Reusable
  server/session plumbing lives in
  [search_agent_lab/week2_runtime.py](search_agent_lab/week2_runtime.py) so the
  Notebook can keep Agent definitions and generated tool contracts visible.
- [search_agent_lab/checks](search_agent_lab/checks) keeps runtime safety out of
  the learner notebook: adk_events.py converts raw ADK events into allowlisted
  rows, and setup.py decides whether those safe rows satisfy the setup check.
- [requirements.lock](requirements.lock) is a hash-locked, offline-tested
  Python 3.11 environment, including the optional ADK evaluation support used
  after the Week 2 checkpoint; its direct inputs are recorded in
  [requirements.in](requirements.in).
- Notebooks and the GitHub validator share the reusable checkpoint engine in
  [search_agent_lab/checkpoints](search_agent_lab/checkpoints). Checkpoint
  definitions, allowlisted evidence, deterministic behavior, and versioned
  word lists remain independent from ADK runtime imports and own only the
  optional public checkpoint after a check succeeds.
- Codename generation requires explicit evidence: notebooks pass evidence
  validated from the real live timeline, while the GitHub validator explicitly
  passes the catalog's public expected evidence for the actual issue author.
- Checkpoint issues are public. Share only the generated codename—never keys,
  .env contents, private traces, or raw model responses.
- The upstream shop_agent.ipynb remains an instructor demo run separately from
  a pinned upstream checkout.
- personalized-shopping is intentionally not part of this first phase.

## Source of truth

The setup is based on Google's current [ADK Python
quickstart](https://adk.dev/get-started/python/) and [ADK installation
guide](https://adk.dev/get-started/installation/). See
[docs/setup.md](docs/setup.md) for the exact local commands and the later
Google Cloud option.
