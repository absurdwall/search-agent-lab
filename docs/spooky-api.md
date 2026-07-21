# Spooky web API

This is the narrow Week 2 browser boundary for Spooky. It accepts one learner
message, runs one turn of the existing glossary agent in a temporary in-memory
ADK session, deletes that session, and returns only the final answer plus links
to the pinned glossary records retrieved during the turn.

It is intentionally not the ADK development API: browsers cannot create, read,
resume, or list ADK sessions, and they cannot receive raw events, traces,
thought content, tool payloads, credentials, or internal exception messages.

## Run locally

Complete `docs/setup.md`, put your Gemini API key in the untracked `.env`, then
start the service from the repository root:

~~~zsh
source .venv/bin/activate
python -m uvicorn search_agent_lab.spooky_api:app \
  --host 127.0.0.1 \
  --port 8001
~~~

This process uses the existing `spooky.root_agent`, its existing instruction,
and its existing `search_glossary` and `get_glossary_terms` tools. It does not
create Google Cloud resources or persist chat history.

## `GET /health`

The health endpoint checks the local HTTP process, not Gemini availability.

Response `200`:

~~~json
{"status":"ok"}
~~~

## `POST /v1/chat`

Request body:

~~~json
{"message":"What is the difference between a Tool and a Skill?"}
~~~

`message` must be a JSON string containing at least one non-whitespace
character and no more than 2,000 characters. Leading and trailing whitespace
is removed before the agent receives it. Extra request fields are rejected.
The call is single-turn and has a 120-second server timeout.

Success response `200`:

~~~json
{
  "answer": "...",
  "sources": [
    {
      "title": "Tool",
      "url": "https://absurdwall.github.io/search-agent-study-group/glossary/#tool"
    },
    {
      "title": "Skill",
      "url": "https://absurdwall.github.io/search-agent-study-group/glossary/#skill"
    }
  ],
  "request_id": "req_..."
}
~~~

`sources` is ordered by the retrieved glossary term order and may be empty when
the glossary has no supporting record. Source titles and URLs are rebuilt from
the committed glossary snapshot using allowlisted term IDs; arbitrary event or
tool fields are never copied into the response.

Every response includes the same opaque ID in the `X-Request-ID` header. The
ID is for correlating a browser-visible failure with safe server diagnostics;
it is not an ADK session handle and cannot be used to retrieve history.

## Error contract

All errors use the same envelope:

~~~json
{
  "error": {
    "code": "EMPTY_MESSAGE",
    "message": "message must contain non-whitespace characters."
  },
  "request_id": "req_..."
}
~~~

| HTTP | Code | Meaning |
| --- | --- | --- |
| `400` | `INVALID_REQUEST` | Malformed JSON, missing/wrong `message`, or extra fields. |
| `400` | `EMPTY_MESSAGE` | `message` is empty or whitespace-only. |
| `413` | `MESSAGE_TOO_LARGE` | `message` exceeds 2,000 characters. |
| `503` | `PROVIDER_UNAVAILABLE` | Gemini credentials, network, quota, capacity, or provider response is unavailable. |
| `504` | `REQUEST_TIMEOUT` | The single turn exceeded 120 seconds. |
| `500` | `INTERNAL_ERROR` | An unexpected server failure occurred. |

Error messages are fixed public text. Provider bodies, exception messages,
event data, and credentials are not returned.

## Browser integration boundary

This development boundary assumes two separately served local processes:

- study-group website: `http://127.0.0.1:8765` or `http://localhost:8765`;
- Spooky API: `http://127.0.0.1:8001`.

Those two local origins and the production GitHub Pages origin
`https://absurdwall.github.io` receive CORS permission by default. Credentials
are disabled; allowed methods are `GET` and `POST`; the only configured request
header is `Content-Type`; browser `OPTIONS` preflight is handled by the CORS
middleware; and `X-Request-ID` is the only exposed response header. CORS is a
browser boundary, not authentication.

An operator may replace the complete allowlist with a comma-separated
`SPOOKY_ALLOWED_ORIGINS` environment variable. Every entry must be an exact
HTTP(S) origin. Startup fails rather than accepting an empty entry, wildcard,
credential, path, query, or fragment.

The website should send one `POST /v1/chat` per learner question and render
only `answer` and the `sources` links. Conversation history, streaming, and
authentication remain out of scope. See [spooky-cloud-run.md](spooky-cloud-run.md)
for the contained Cloud Run deployment boundary.
