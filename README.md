# Search Agent Lab

A small, hands-on Google ADK learner repository for the Search Agent Study Group.

This repository deliberately starts with onboarding only. It holds a
credential-free setup notebook and a tested dependency lock; later it can grow
into small starter code, tests, and assignments. It does not own study-group
planning or slides, and it does not copy Google's shopping-agent demo.

## Start here

Follow [docs/setup.md](docs/setup.md) to create an isolated local environment,
pass the offline setup check, and optionally configure your own Gemini API key.
The recommended first path uses the Gemini API directly; Google Cloud / Vertex
is a later option.

After a successful optional live run, Week 1 learners can generate a
deterministic agent codename and a prefilled public GitHub Issue Form. That
checkpoint is a cheerful honor-system engagement mechanism, not authentication
or formal grading.

## Safety and scope

- Copy .env.example to .env locally; never commit .env or credentials.
- [notebooks/00_setup_check.ipynb](notebooks/00_setup_check.ipynb) defaults to
  a credential-free offline mode before any live model call.
- [requirements.lock](requirements.lock) is a hash-locked, offline-tested
  Python 3.11 environment; its direct inputs are recorded in
  [requirements.in](requirements.in).
- Notebooks and the GitHub validator share the reusable checkpoint engine in
  [search_agent_lab/checkpoints](search_agent_lab/checkpoints). Checkpoint
  definitions, deterministic behavior, and versioned word lists are separate,
  so later weeks do not need copied modules or workflows.
- [search_agent_lab/week1_checkpoint.py](search_agent_lab/week1_checkpoint.py)
  remains a small compatibility facade for the current setup notebook.
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
