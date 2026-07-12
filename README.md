# Search Agent Lab

A small, hands-on Google ADK learner repository for the Search Agent Study Group.

This repository starts with a small onboarding foundation and Course Agent v0,
a glossary-only question-answering demo. It holds learner notebooks, starter
code, deterministic tests, and a tested dependency lock. It does not own
study-group planning or slides, and it does not copy Google's shopping-agent
demo.

## Start here

Follow [docs/setup.md](docs/setup.md) to create an isolated local environment,
pass the local environment check, and optionally configure your own Gemini API
key.
The recommended first path uses the Gemini API directly; Google Cloud / Vertex
is a later option.

After setup, open
[notebooks/01_glossary_qa.ipynb](notebooks/01_glossary_qa.ipynb) for Course
Agent v0. It searches a pinned public course glossary with two deterministic
tools, then runs one real question through a shared local ADK server.

Start that server manually from the repository root and keep the terminal open
for the complete demo:

~~~zsh
source .venv/bin/activate

adk api_server \
  --with_ui \
  --session_service_uri=memory:// \
  --no-reload \
  --port 8000 \
  .
~~~

The Notebook and [ADK Web](http://127.0.0.1:8000) use that one server and the
same in-memory session. The Notebook shows a small allowlisted timeline; ADK
Web provides complete local Request, Response, Event, and Graph inspection.
ADK Web is a development and teaching interface, not the final deployed
website assistant.

After a successful optional live run, Week 1 learners can generate a
deterministic, evidence-bound agent codename and a prefilled public GitHub
Issue Form. That checkpoint is a cheerful honor-system engagement mechanism,
not authentication or formal grading; all expected evidence remains public.

## Safety and scope

- Copy .env.example to .env locally; never commit .env or credentials.
- [notebooks/00_setup_check.ipynb](notebooks/00_setup_check.ipynb) always runs
  an honest local environment check. Without a key it stops with a friendly
  waiting message; with a key it automatically attempts one real ADK run.
- [notebooks/01_glossary_qa.ipynb](notebooks/01_glossary_qa.ipynb) is Course
  Agent v0: a pinned-glossary QA demo using the shared ADK server and session.
- [search_agent_lab/checks](search_agent_lab/checks) keeps runtime safety out of
  the learner notebook: adk_events.py converts raw ADK events into allowlisted
  rows, and setup.py decides whether those safe rows satisfy the setup check.
- [requirements.lock](requirements.lock) is a hash-locked, offline-tested
  Python 3.11 environment; its direct inputs are recorded in
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
