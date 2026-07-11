# Local setup

This is the deliberately small first-run path for Search Agent Lab. It creates
an isolated Python environment, installs the offline-tested Google ADK stack, passes a
credential-free notebook check, and then optionally uses your own Gemini API
key. It does not create a product agent, deploy anything, copy the shopping
demo, or require Google Cloud.

Google's current [ADK Python quickstart](https://adk.dev/get-started/python/)
supports Python 3.10 or later and recommends a virtual environment. This
repository's hash-locked learner path was dogfooded on macOS with CPython
3.11.5, so use Python 3.11 for this first run.

## 1. Create the offline-tested local environment

From the repository root:

~~~zsh
python3.11 --version
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python -m pip check
adk --version
~~~

The direct, reviewed inputs live in requirements.in. requirements.lock contains
the exact transitive resolution and hashes, so do not replace the install
command with a bare unpinned pip install.

## 2. Pass the offline setup check

The default check has no API request and does not require .env. It calls a tiny
deterministic local tool and renders only a redacted timeline:

~~~text
user input → agent → tool call → tool result → final answer
~~~

Open notebooks/00_setup_check.ipynb in a notebook-capable editor and select
the .venv Python kernel, then run all cells. The final offline cell must print:

~~~text
Offline setup check: PASS
~~~

This is Run 1. Keep RUN_LIVE_CHECK set to False. The notebook will not produce
the Week 1 achievement, agent codename, or submission link in this mode.

For a headless, non-destructive verification, install a local-only kernel and
write the executed notebook to a temporary path:

~~~zsh
python -m ipykernel install --prefix "$VIRTUAL_ENV" --name search-agent-lab --display-name "Python (search-agent-lab)"
JUPYTER_PATH="$VIRTUAL_ENV/share/jupyter" jupyter execute notebooks/00_setup_check.ipynb --output /tmp/00_setup_check.executed.ipynb --kernel_name search-agent-lab --timeout=120
~~~

## 3. Add your Gemini API key locally

The Gemini API / Google AI Studio route is the recommended first live
experience because it does not require a Google Cloud project. Create a key in
[Google AI Studio](https://aistudio.google.com/apikey), then create your
untracked local file:

~~~zsh
cp .env.example .env
open -e .env
~~~

Set only your own value:

~~~dotenv
GOOGLE_API_KEY="your-own-key-goes-here"
~~~

Do not paste the key into a terminal command, notebook output, chat, or Git.
The notebook loads .env locally and reports only whether a credential was
detected; it never prints the value.

## 4. Run the optional live checkpoint

This is Run 2. In notebooks/00_setup_check.ipynb:

1. Set GITHUB_USERNAME explicitly to your public GitHub login.
2. Change RUN_LIVE_CHECK from False to True.
3. Run all cells again.

The check uses the current quickstart model alias gemini-flash-latest and one
ADK runner invocation. Tool use can involve more than one underlying model
exchange, so this is intentionally a small connectivity check rather than a
cost or performance test.

The achievement and codename appear only when all three conditions pass:

- the notebook detects your credential locally;
- the live ADK invocation completes; and
- the redacted timeline contains a real tool call, tool result, and final
  answer event.

On success, the notebook prints:

~~~text
🎉 The agent found its first tool!
~~~

It then generates a deterministic codename in this format:

~~~text
Emoji Color Animal — Agent Title
~~~

The seed includes the normalized GitHub username and the versioned Week 1
checkpoint. The reusable engine lives in search_agent_lab/checkpoints: the
catalog defines each checkpoint, core.py owns generation and validation, and
words.py keeps versioned word lists. The current notebook's Week 1 import is a
compatibility facade over that same engine, so its v1 codenames stay stable.

The rendered timeline exposes only:

- the fixed user input and agent name;
- the allowlisted local tool name and public topic;
- the allowlisted deterministic result; and
- a final-response acknowledgement with the content omitted.

It does not serialize raw events, display private reasoning, print hidden
instructions, or expose error details. If the live check does not complete,
run offline mode again first, then verify key setup, network, quota, and model
access without sharing the key.

The committed notebook is intentionally output-free. If a graphical editor
saves cell outputs while you explore, clear them before any commit:

~~~zsh
jupyter nbconvert --ClearOutputPreprocessor.enabled=True --to notebook --inplace notebooks/00_setup_check.ipynb
~~~

## 5. Optional public Issue Form

After a successful live checkpoint, the notebook prints a prefilled GitHub
Issue Form URL containing the checkpoint ID, checkpoint phrase, generated
codename, and issue title.
Open it while signed in to the same GitHub account entered as GITHUB_USERNAME,
review the public fields, check the honor-system confirmation, and submit.

The validator recomputes the expected codename from the actual issue author:

- valid submissions receive checkpoint, passed, and week-01 labels, a cheerful
  status comment, and automatic closure;
- invalid submissions receive checkpoint and needs-fix labels, helpful editing
  instructions, and remain open; and
- edits and reopened issues are revalidated, with the opposite status label
  removed. The validator updates its existing status comment rather than
  adding a new comment on every edit.

Later checkpoints use this same public form and workflow. Maintainers normally
add one data entry to search_agent_lab/checkpoints/catalog.py, then call the
shared checkpoint API from the relevant notebook; hashing, parsing, labels,
comments, and Action behavior stay centralized.

This is optional, public, and based on learner honesty. It is not identity
authentication, access control, certification, or formal grading. Do not put
API keys, .env contents, personal paths, private traces, raw events, or model
responses in the issue.

## Later option: Google Cloud / Vertex

Do not use this path for the first learner setup. It adds a Google Cloud
project, enabled APIs, the gcloud CLI, Application Default Credentials, and
project/location configuration. When it is needed, follow Google's [Google
Cloud ADK guide](https://adk.dev/get-started/google-cloud/) rather than adding
service-account keys to this repository. For local development, the guide uses:

~~~zsh
gcloud auth application-default login
~~~

with local (untracked) environment settings such as:

~~~dotenv
GOOGLE_GENAI_USE_ENTERPRISE=TRUE
GOOGLE_CLOUD_PROJECT="your-project-id"
GOOGLE_CLOUD_LOCATION="us-central1"
~~~

## Maintainer note: updating the lock

Learners do not need uv. The current lock was generated with uv 0.9.17 using:

~~~zsh
uv pip compile --python-version 3.11 --universal --generate-hashes requirements.in -o requirements.lock
~~~

Regenerate it only after intentionally testing the changed environment in a
fresh Python 3.11 virtual environment and rerunning the offline notebook.
