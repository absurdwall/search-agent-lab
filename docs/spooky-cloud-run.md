# Spooky Cloud Run deployment

This runbook deploys only the single-turn FastAPI service in
`search_agent_lab/spooky_api.py`. It does not deploy ADK Web or an Agent
Platform hosted agent, and it does not expose ADK sessions, events, traces,
tool payloads, exceptions, credentials, or OpenAPI documentation.

## Fixed deployment contract

| Setting | Value |
| --- | --- |
| Project | `search-agent-lab` (`759544311265`) |
| Service | `spooky-api` |
| Cloud Run region | `us-east1` |
| Model location | `global` |
| Access | Private verification first; public HTTPS only after it passes |
| Billing | Request-based with CPU throttling |
| Instances | Minimum `0`; service maximum `2` |
| Concurrency | `1` request per instance |
| Request timeout | `180s` |
| Resources | `1` CPU; `512Mi` memory |
| Runtime identity | `spooky-api-runtime@search-agent-lab.iam.gserviceaccount.com` |
| Runtime role | Vertex AI User (`roles/aiplatform.user`) only |
| Model auth | Cloud Run service identity and ADC; no API key or key file |
| Default CORS | Two documented localhost origins plus `https://absurdwall.github.io` |

Concurrency is intentionally one because the process shares one ADK Runner and
one in-memory session service while a request can wait on serial model/tool
turns. The service maximum of two bounds simultaneous provider calls. The
2,000-character request limit bounds browser-controlled input. Do not add an
output-token cap in this deployment: it would also change the learner agent and
could truncate thinking or tool turns.

CORS, instance limits, and budget alerts are not authentication or hard
spending caps. A non-browser client can ignore CORS, and serial requests can
still consume model credit. This limited public exposure is an accepted risk
for the small study-group service. Cloud Run compute and Vertex AI inference
are separate billable services in the same project.

## Keep setup and workload identities separate

The same human can perform more than one human step, but each grant must remain
purpose-specific. Never copy human/setup permissions onto a build or runtime
service account.

| Identity | Purpose | Required access |
| --- | --- | --- |
| Setup administrator | Enable APIs, create service accounts, change IAM, configure public access, and create the budget | Existing Owner/Billing administration, or the corresponding Service Usage Admin, Service Account Admin, Project IAM Admin, Cloud Run Admin, and billing-budget permissions |
| Source deployer | Submit the source deployment and attach the runtime identity | `roles/run.sourceDeveloper` and `roles/serviceusage.serviceUsageConsumer` on the project; `roles/iam.serviceAccountUser` on `spooky-api-runtime`; `iam.serviceAccounts.actAs` on the actual build identity when the organization/build policy requires it |
| Direct smoke caller | Make the one pre-build publisher-model request with the signed-in user's OAuth token | `roles/aiplatform.user`, or equivalent `aiplatform.endpoints.predict`, on this project; remove a task-only grant after the smoke if it is no longer needed |
| Build identity | Build the container from the pinned source | `roles/run.builder` only on the project |
| Runtime identity | Run the container and call the Google Cloud AI backend | `roles/aiplatform.user` only on the project |

This dedicated project uses the Compute Engine default service account as the
build identity:

~~~text
759544311265-compute@developer.gserviceaccount.com
~~~

New organizations normally do not grant Editor to default service accounts.
Do not add Editor and do not give this build identity Vertex AI access. A
custom build identity can be considered later as a separate hardening task.

After the private service exists, its tester also needs `run.routes.invoke`,
normally through a service-scoped Cloud Run Invoker grant. Do not create that
binding before the service exists. Disabling or re-enabling the public invoker
check requires `run.services.setIamPolicy`, normally through Cloud Run Admin.
Keep these human permissions off the build and runtime identities.

Google's current references are the
[source deployment roles](https://docs.cloud.google.com/run/docs/reference/iam/roles#additional-configuration),
[service identity guide](https://docs.cloud.google.com/run/docs/securing/service-identity),
[Vertex AI quickstart](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/quickstart),
and [public access guide](https://docs.cloud.google.com/run/docs/authenticating/public).

## Browser checkpoints before deployment

Complete one checkpoint at a time in Google Cloud Console and verify the
visible result before continuing.

1. Confirm project `search-agent-lab`, its Free Trial billing linkage, and the
   deployment locations above.
2. As the setup administrator, enable Agent Platform / Vertex AI API
   (`aiplatform.googleapis.com`), Cloud Run Admin API, Cloud Build API,
   Artifact Registry API, IAM API, and Service Usage API. Cloud Run API
   enablement creates the Compute Engine default service account if it is not
   present.
3. As the setup administrator, create the user-managed service account
   `spooky-api-runtime`. Grant it only Vertex AI User on this project. Do not
   create a key for it.
4. Grant the source deployer the two project roles and Service Account User on
   `spooky-api-runtime` described above.
5. In Cloud Shell, confirm the regional default build identity with `gcloud
   builds get-default-service-account --region us-east1`; it must be the
   Compute Engine identity shown above. Grant that identity only Cloud Run
   Builder. If the source submitter is required to act as that build identity,
   grant the submitter Service Account User on this exact service account, not
   on the runtime identity as a substitute.
6. Ensure the human performing the direct model smoke has Vertex AI User or
   equivalent predict permission. Do not grant this role to the build identity.
7. Create a small budget alert scoped to this project. Record its amount and
   thresholds. A budget alert notifies; it does not stop usage.
8. Review the final diff, tests, exact commit SHA, deploy settings, and public
   exposure before submitting a build. Do not create a Cloud Run Invoker
   binding yet; the service does not exist.

Do not create a Gemini or Agent Platform API key, a Secret Manager Gemini
secret, a service-account key file, or an Agent Platform hosted agent. Never
set `GOOGLE_APPLICATION_CREDENTIALS` on Cloud Run.

## Cloud Shell preflight

Open Cloud Shell in project `search-agent-lab`. These variables are not
secrets:

~~~zsh
TASK_PROJECT="search-agent-lab"
TASK_PROJECT_NUMBER="759544311265"
TASK_REGION="us-east1"
TASK_MODEL_LOCATION="global"
TASK_SERVICE="spooky-api"
TASK_RUNTIME_SA="spooky-api-runtime@${TASK_PROJECT}.iam.gserviceaccount.com"
TASK_BUILD_SA="${TASK_PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud config set project "$TASK_PROJECT"
gcloud builds get-default-service-account \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION"
~~~

Stop if the reported default build identity differs from `TASK_BUILD_SA`.
Do not silently grant roles to another identity.

Before building, make one controlled direct request to the intended publisher
model. `gcloud auth print-access-token` uses the signed-in human's OAuth
credential. This check validates that caller's authorization plus the global
endpoint, model, quota, and billing path; it does not test the future Cloud Run
runtime identity and it does not deploy an agent:

~~~zsh
TASK_MODEL="gemini-3.5-flash"

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://aiplatform.googleapis.com/v1/projects/${TASK_PROJECT}/locations/${TASK_MODEL_LOCATION}/publishers/google/models/${TASK_MODEL}:generateContent" \
  -d '{"contents":[{"role":"user","parts":[{"text":"Reply with exactly READY."}]}]}' \
  > /tmp/spooky-model-smoke.json

jq -e '.candidates[0].content.parts | length > 0' \
  /tmp/spooky-model-smoke.json > /dev/null
~~~

The later private `/v1/chat` test is the check that validates the Cloud Run
service identity's ADC and runtime IAM. If this direct request reports model
not found, unsupported location, quota, billing, or permission errors, stop and
report the exact safe error category. Do not change the model or location
silently.

## Pin the exact source

The verified feature-branch commit must be pushed before Cloud Shell deploys
it. Record the full 40-character SHA locally. In Cloud Shell, clone the public
repository and check out that exact commit in detached mode:

~~~zsh
git clone https://github.com/absurdwall/search-agent-lab.git
cd search-agent-lab

TASK_COMMIT="FULL_VERIFIED_40_CHARACTER_SHA"
git fetch --all --prune
git checkout --detach "$TASK_COMMIT"

test "$(git rev-parse HEAD)" = "$TASK_COMMIT"
test -z "$(git status --porcelain)"
~~~

Do not deploy a movable branch name and do not continue with a dirty checkout.

## Deploy privately first

The locked ADK runtime uses `GOOGLE_GENAI_USE_ENTERPRISE=True` as its preferred
Google Cloud backend switch. `GOOGLE_GENAI_USE_VERTEXAI` is only a legacy
fallback and is not set on Cloud Run.

~~~zsh
gcloud run deploy "$TASK_SERVICE" \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --source . \
  --service-account "$TASK_RUNTIME_SA" \
  --set-env-vars "GOOGLE_GENAI_USE_ENTERPRISE=True,GOOGLE_CLOUD_PROJECT=${TASK_PROJECT},GOOGLE_CLOUD_LOCATION=${TASK_MODEL_LOCATION}" \
  --port 8080 \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 1 \
  --timeout 180s \
  --cpu-throttling \
  --min 0 \
  --max 2 \
  --ingress all \
  --invoker-iam-check
~~~

Keep the invoker IAM check enabled. Confirm there is no `allUsers` Cloud Run
Invoker binding before testing. Only now, if the signed-in tester lacks
`run.routes.invoke`, the setup administrator grants that person Cloud Run
Invoker on this service (not at project scope):

~~~zsh
TASK_TESTER="user:$(gcloud config get-value account)"

gcloud run services add-iam-policy-binding "$TASK_SERVICE" \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --member "$TASK_TESTER" \
  --role roles/run.invoker
~~~

Capture the endpoint without printing credentials:

~~~zsh
TASK_ENDPOINT="$(gcloud run services describe "$TASK_SERVICE" \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --format='value(status.url)')"
~~~

Run one authenticated health check and one representative Tool-versus-Skill
chat. Save bodies only in temporary Cloud Shell files and record status and
shape, not model text or learner content:

~~~zsh
spooky_header_value() {
  local header_name="$1"
  local header_file="$2"
  awk -F ': *' -v wanted="$header_name" '
    tolower($1) == tolower(wanted) {
      sub(/\r$/, "", $2)
      value = $2
    }
    END { print value }
  ' "$header_file"
}

(
  set -euo pipefail

  spooky_private_cleanup() {
    unset TASK_ID_TOKEN 2>/dev/null || true
    rm -f -- \
      /tmp/spooky-model-smoke.json \
      /tmp/spooky-private-health-headers.txt \
      /tmp/spooky-private-health.json \
      /tmp/spooky-private-chat-headers.txt \
      /tmp/spooky-private-chat.json
  }
  trap spooky_private_cleanup EXIT

  TASK_ID_TOKEN="$(gcloud auth print-identity-token)"

  TASK_PRIVATE_HEALTH_STATUS="$(curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer ${TASK_ID_TOKEN}" \
    -H 'Origin: https://absurdwall.github.io' \
    -D /tmp/spooky-private-health-headers.txt \
    -o /tmp/spooky-private-health.json \
    -w '%{http_code}' \
    "$TASK_ENDPOINT/health")"

  test "$TASK_PRIVATE_HEALTH_STATUS" = "200"
  jq -e '.status == "ok"' /tmp/spooky-private-health.json > /dev/null
  test -n "$(spooky_header_value \
    'X-Request-ID' /tmp/spooky-private-health-headers.txt)"

  TASK_PRIVATE_CHAT_STATUS="$(curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer ${TASK_ID_TOKEN}" \
    -H 'Origin: https://absurdwall.github.io' \
    -H 'Content-Type: application/json' \
    -D /tmp/spooky-private-chat-headers.txt \
    -o /tmp/spooky-private-chat.json \
    -d '{"message":"What is the difference between a Tool and a Skill?"}' \
    -w '%{http_code}' \
    "$TASK_ENDPOINT/v1/chat")"

  test "$TASK_PRIVATE_CHAT_STATUS" = "200"
  jq -e '
    (.answer | type == "string" and length > 0) and
    (.request_id | type == "string" and startswith("req_")) and
    any(.sources[]; .url | endswith("#tool")) and
    any(.sources[]; .url | endswith("#skill"))
  ' /tmp/spooky-private-chat.json > /dev/null

  TASK_PRIVATE_JSON_REQUEST_ID="$(jq -r '.request_id' \
    /tmp/spooky-private-chat.json)"
  TASK_PRIVATE_HEADER_REQUEST_ID="$(spooky_header_value \
    'X-Request-ID' /tmp/spooky-private-chat-headers.txt)"
  test "$TASK_PRIVATE_JSON_REQUEST_ID" = "$TASK_PRIVATE_HEADER_REQUEST_ID"

  printf 'private-verification=passed\n'
)
~~~

Do not continue unless this fail-closed block exits zero and prints
`private-verification=passed`. Its `EXIT` trap removes the temporary evidence
and unsets the token whether an assertion passes or fails.

Require HTTP 200, the safe success envelope, a nonempty answer, both expected
canonical sources, matching `X-Request-ID`, and no model, permission, quota, or
`MAX_TOKENS` error. Stop on any failure; do not make the service public.

## Verify configuration before public access

Export the service configuration to a temporary file:

~~~zsh
gcloud run services describe "$TASK_SERVICE" \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --format=export > /tmp/spooky-service.yaml

if grep -Eq 'GOOGLE_API_KEY|GEMINI_API_KEY|GOOGLE_APPLICATION_CREDENTIALS' \
  /tmp/spooky-service.yaml; then
  echo "Forbidden credential environment name found" >&2
  exit 1
fi

if grep -Eq 'secretKeyRef:|run.googleapis.com/secrets' \
  /tmp/spooky-service.yaml; then
  echo "Unexpected secret binding found" >&2
  exit 1
fi
~~~

Also verify the ready revision, image digest, runtime identity, three intended
non-secret environment variables, request-based billing, CPU throttling,
min/max instances, concurrency, timeout, CPU, memory, and ingress in the Cloud
Run Console. Confirm the build identity has no Vertex role and the runtime
identity has no build/deployer role.

## Diagnose a provider failure without moving traffic

Keep the serving revision private and at 100% traffic. After the diagnostic
change has passed code review and is available at a new pushed, detached full
commit SHA, record the current serving revision and deploy the diagnostic
revision through this fail-closed gate:

~~~zsh
(
  set -euo pipefail

  TASK_DIAG_BEFORE="/tmp/spooky-diag-before.json"
  TASK_DIAG_AFTER="/tmp/spooky-diag-after.json"
  TASK_DIAG_POLICY="/tmp/spooky-diag-policy.json"

  spooky_diag_cleanup() {
    rm -f -- \
      "$TASK_DIAG_BEFORE" \
      "$TASK_DIAG_AFTER" \
      "$TASK_DIAG_POLICY"
  }

  spooky_diag_recover() {
    local recovery_failed=0
    set +e

    gcloud run services update "$TASK_SERVICE" \
      --project "$TASK_PROJECT" \
      --region "$TASK_REGION" \
      --invoker-iam-check || recovery_failed=1

    gcloud run services update-traffic "$TASK_SERVICE" \
      --project "$TASK_PROJECT" \
      --region "$TASK_REGION" \
      --to-revisions "${TASK_PRIOR_REVISION}=100" || recovery_failed=1

    gcloud run services update-traffic "$TASK_SERVICE" \
      --project "$TASK_PROJECT" \
      --region "$TASK_REGION" \
      --remove-tags provider-diag || recovery_failed=1

    gcloud run services describe "$TASK_SERVICE" \
      --project "$TASK_PROJECT" \
      --region "$TASK_REGION" \
      --format=json > "$TASK_DIAG_AFTER" || recovery_failed=1
    gcloud run services get-iam-policy "$TASK_SERVICE" \
      --project "$TASK_PROJECT" \
      --region "$TASK_REGION" \
      --format=json > "$TASK_DIAG_POLICY" || recovery_failed=1

    jq -e --arg prior "$TASK_PRIOR_REVISION" '
      any(.status.traffic[]?;
        .revisionName == $prior and (.percent // 0) == 100) and
      ([.status.traffic[]? | select(.tag == "provider-diag")] | length == 0) and
      ((.metadata.annotations["run.googleapis.com/invoker-iam-disabled"]
        // "false") == "false")
    ' "$TASK_DIAG_AFTER" > /dev/null || recovery_failed=1
    jq -e '
      [.bindings[]?.members[]?] | index("allUsers") == null
    ' "$TASK_DIAG_POLICY" > /dev/null || recovery_failed=1

    if (( recovery_failed == 0 )); then
      printf 'diagnostic-drift-recovery=passed\n'
    else
      printf 'diagnostic-drift-recovery=failed\n' >&2
    fi
    set -e
    return "$recovery_failed"
  }

  spooky_diag_exit() {
    local exit_status="$?"
    trap - EXIT
    if (( exit_status != 0 )); then
      spooky_diag_recover || true
    fi
    spooky_diag_cleanup
    exit "$exit_status"
  }

  test "$(git rev-parse HEAD)" = "$TASK_COMMIT"
  test -z "$(git status --porcelain)"

  gcloud run services describe "$TASK_SERVICE" \
    --project "$TASK_PROJECT" \
    --region "$TASK_REGION" \
    --format=json > "$TASK_DIAG_BEFORE"
  TASK_PRIOR_REVISION="$(jq -er '
    [.status.traffic[]?
      | select((.percent // 0) == 100)
      | .revisionName]
    | if length == 1 then .[0]
      else error("Expected exactly one 100% serving revision") end
  ' "$TASK_DIAG_BEFORE")"

  trap spooky_diag_exit EXIT

  gcloud run deploy "$TASK_SERVICE" \
    --project "$TASK_PROJECT" \
    --region "$TASK_REGION" \
    --source . \
    --service-account "$TASK_RUNTIME_SA" \
    --set-env-vars "GOOGLE_GENAI_USE_ENTERPRISE=True,GOOGLE_CLOUD_PROJECT=${TASK_PROJECT},GOOGLE_CLOUD_LOCATION=${TASK_MODEL_LOCATION}" \
    --port 8080 \
    --cpu 1 \
    --memory 512Mi \
    --concurrency 1 \
    --timeout 180s \
    --cpu-throttling \
    --min 0 \
    --max 2 \
    --ingress all \
    --invoker-iam-check \
    --no-traffic \
    --tag provider-diag \
    --quiet

  gcloud run services describe "$TASK_SERVICE" \
    --project "$TASK_PROJECT" \
    --region "$TASK_REGION" \
    --format=json > "$TASK_DIAG_AFTER"
  gcloud run services get-iam-policy "$TASK_SERVICE" \
    --project "$TASK_PROJECT" \
    --region "$TASK_REGION" \
    --format=json > "$TASK_DIAG_POLICY"

  TASK_DIAG_REVISION="$(jq -er '.status.latestCreatedRevisionName' \
    "$TASK_DIAG_AFTER")"
  TASK_TAGGED_URL="$(jq -er --arg revision "$TASK_DIAG_REVISION" '
    .status.traffic[]
    | select(.tag == "provider-diag" and .revisionName == $revision)
    | .url
  ' "$TASK_DIAG_AFTER")"

  jq -e --arg prior "$TASK_PRIOR_REVISION" \
    --arg diagnostic "$TASK_DIAG_REVISION" '
    any(.status.traffic[]?;
      .revisionName == $prior and (.percent // 0) == 100) and
    any(.status.traffic[]?;
      .revisionName == $diagnostic and .tag == "provider-diag" and
      (.percent // 0) == 0) and
    ((.metadata.annotations["run.googleapis.com/invoker-iam-disabled"]
      // "false") == "false")
  ' "$TASK_DIAG_AFTER" > /dev/null
  jq -e '
    [.bindings[]?.members[]?] | index("allUsers") == null
  ' "$TASK_DIAG_POLICY" > /dev/null

  TASK_TAGGED_UNAUTH_STATUS="$(curl --silent --show-error \
    --output /dev/null \
    --write-out '%{http_code}' \
    "$TASK_TAGGED_URL/health")"
  test "$TASK_TAGGED_UNAUTH_STATUS" = "403"

  printf 'PRIOR_REVISION=%s\n' "$TASK_PRIOR_REVISION"
  printf 'DIAGNOSTIC_REVISION=%s\n' "$TASK_DIAG_REVISION"
  printf 'DIAGNOSTIC_TAGGED_URL=%s\n' "$TASK_TAGGED_URL"
  printf 'diagnostic-deployment-gate=passed\n'
)
~~~

Do not make an authenticated diagnostic request unless the block exits zero
and prints `diagnostic-deployment-gate=passed`. Copy the three printed safe
revision/URL values into the corresponding shell variables before testing.
If any assertion or deployment step fails, the `EXIT` trap immediately restores
the invoker check, the recorded prior revision at 100%, and removes the
diagnostic tag. Do not continue if recovery does not print
`diagnostic-drift-recovery=passed`.

The complete experiment has one global request budget. The successful
no-reproduction path makes exactly four chat calls: two first-stage calls and
two second-stage calls. Every path is limited to five chat calls because the
first `503` or `504` may receive the experiment's only immediate manual retry.
That retry must immediately follow the failed call. Then stop, even if the
retry succeeds. Do not add an automatic application retry or migrate traffic
as part of diagnosis.

The first-stage experiment is limited to one baseline chat and, only after the
tagged revision reaches `active=0, idle=1`, one chat without a preceding health
request. Any non-`200` first-stage response ends the first stage and prohibits
the second stage. A `503` or `504` follows the single-retry rule above. Any
other non-`200`, curl/auth/transport failure, malformed response envelope,
request-ID mismatch, or monitoring ambiguity stops the complete experiment
immediately and must not be retried.

If both first-stage chats return `200`, record only that the failure was not
reproduced during an idle-instance resume. `active=0, idle=1` is not a true
scale-to-zero cold start, so it does not prove that the provider failure is
fixed. Keep the prior revision at 100%, keep the diagnostic revision at 0%,
and keep the service private.

Only after this no-reproduction path has passed review may a second-stage
experiment run. It is limited to two true scale-to-zero cycles and must follow
all of these rules:

- Before each request, use Cloud Monitoring without invoking the service and
  require `active=0` and `idle=0` from the same aligned sample timestamp or
  aligned interval, strictly after the preceding request completed. The metric
  samples every 60 seconds and can take up to 120 seconds to appear. Separately
  fresh zeroes with different timestamps do not prove scale-to-zero. A missing
  series, missing point, stale sample, mismatched timestamp, or ambiguous
  interval is not zero and stops the experiment. An idle instance can remain
  available for about 15 minutes; wait and recheck instead of sending a request
  while either aligned fresh value is nonzero.
- Recheck immediately before each request that the prior revision still has
  100% traffic, the `provider-diag` revision still has 0%, the invoker IAM
  check is enabled, and `allUsers` is absent. Any drift ends the experiment.
- Send exactly one authenticated tagged `POST /v1/chat` per cycle. Do not call
  `/health` first, run requests concurrently, or perform a load test. A 0%
  traffic tagged revision does not count toward the service-level maximum, so
  the diagnostic revision's own instance limit is the applicable safety bound.
- Record the request start time. After the response, require revision-scoped
  Cloud Run system startup evidence timestamped at or after that start time.
  Project only the startup timestamp and revision name. If startup evidence is
  missing or ambiguous, the call does not count as a cold-start result; stop
  without retrying or starting another cycle.
- If a corroborated cold request returns `200`, do not retry it. If the first
  `503` or `504` occurs, read only the allowlisted classification fields, apply
  the global single-retry rule, and then end every remaining cycle.

After the aligned-zero and drift guards pass, run one cold cycle with this
fail-fast block. It records a fresh RFC3339 start immediately before `curl` and
an end immediately after the response. It then makes 12 read-only polling
queries separated by 10-second waits, followed by one final read; query runtime
is additional. No poll invokes an endpoint. Every read reuses the same closed
event-time window; never move either bound. Exactly one revision-scoped
`AUTOSCALING` startup row in the final result corroborates the cycle. The query
filters the fixed Cloud Run system message but projects only the safe timestamp
and revision name:

~~~zsh
(
  set -euo pipefail

  TASK_COLD_HEADERS="/tmp/spooky-cold-headers.txt"
  TASK_COLD_BODY="/tmp/spooky-cold-body.json"

  spooky_cold_cleanup() {
    unset TASK_COLD_TOKEN 2>/dev/null || true
    rm -f -- "$TASK_COLD_HEADERS" "$TASK_COLD_BODY"
  }
  trap spooky_cold_cleanup EXIT

  TASK_COLD_TOKEN="$(gcloud auth print-identity-token)"
  TASK_COLD_REQUEST_START="$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)"
  TASK_COLD_STATUS="$(curl --silent --show-error \
    --max-time 190 \
    -H "Authorization: Bearer ${TASK_COLD_TOKEN}" \
    -H 'Origin: https://absurdwall.github.io' \
    -H 'Content-Type: application/json' \
    -D "$TASK_COLD_HEADERS" \
    -o "$TASK_COLD_BODY" \
    -w '%{http_code}' \
    -d '{"message":"What is the difference between a Tool and a Skill?"}' \
    "$TASK_TAGGED_URL/v1/chat")"
  TASK_COLD_REQUEST_END="$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)"

  TASK_COLD_JSON_REQUEST_ID="$(jq -er '.request_id' "$TASK_COLD_BODY")"
  TASK_COLD_HEADER_REQUEST_ID="$(awk '
    BEGIN { IGNORECASE=1 }
    /^X-Request-ID:/ {
      sub(/^[^:]*:[[:space:]]*/, "")
      sub(/\r$/, "")
      value=$0
    }
    END { print value }
  ' "$TASK_COLD_HEADERS")"
  test -n "$TASK_COLD_HEADER_REQUEST_ID"
  test "$TASK_COLD_JSON_REQUEST_ID" = "$TASK_COLD_HEADER_REQUEST_ID"

  case "$TASK_COLD_STATUS" in
    200)
      jq -e '
        (.answer | type == "string" and length > 0) and
        any(.sources[]; .url | endswith("#tool")) and
        any(.sources[]; .url | endswith("#skill"))
      ' "$TASK_COLD_BODY" > /dev/null
      ;;
    503)
      jq -e '.error.code == "PROVIDER_UNAVAILABLE"' \
        "$TASK_COLD_BODY" > /dev/null
      ;;
    504)
      jq -e '.error.code == "REQUEST_TIMEOUT"' \
        "$TASK_COLD_BODY" > /dev/null
      ;;
    *)
      printf 'unexpected-cold-status=%s\n' "$TASK_COLD_STATUS" >&2
      exit 1
      ;;
  esac

  TASK_STARTUP_FILTER="resource.type=\"cloud_run_revision\" AND \
resource.labels.service_name=\"${TASK_SERVICE}\" AND \
resource.labels.revision_name=\"${TASK_DIAG_REVISION}\" AND \
timestamp>=\"${TASK_COLD_REQUEST_START}\" AND \
timestamp<=\"${TASK_COLD_REQUEST_END}\" AND \
logName=\"projects/${TASK_PROJECT}/logs/run.googleapis.com%2Fvarlog%2Fsystem\" AND \
textPayload:\"Starting new instance. Reason: AUTOSCALING\""

  TASK_STARTUP_ROWS=""
  TASK_STARTUP_COUNT=0

  spooky_read_startup_rows() {
    gcloud logging read "$TASK_STARTUP_FILTER" \
      --project "$TASK_PROJECT" \
      --limit 2 \
      --order=asc \
      --format='value(timestamp,resource.labels.revision_name)'
  }

  for TASK_STARTUP_ATTEMPT in {1..12}; do
    TASK_STARTUP_ROWS="$(spooky_read_startup_rows)"
    TASK_STARTUP_COUNT="$(printf '%s\n' "$TASK_STARTUP_ROWS" \
      | awk 'NF { count += 1 } END { print count + 0 }')"
    test "$TASK_STARTUP_COUNT" -le 1
    if test "$TASK_STARTUP_ATTEMPT" != 12; then
      sleep 10
    fi
  done

  TASK_STARTUP_ROWS="$(spooky_read_startup_rows)"
  TASK_STARTUP_COUNT="$(printf '%s\n' "$TASK_STARTUP_ROWS" \
    | awk 'NF { count += 1 } END { print count + 0 }')"
  test "$TASK_STARTUP_COUNT" = 1
  printf 'COLD_REQUEST_START=%s\n' "$TASK_COLD_REQUEST_START"
  printf 'COLD_REQUEST_END=%s\n' "$TASK_COLD_REQUEST_END"
  printf 'COLD_STATUS=%s\n' "$TASK_COLD_STATUS"
  printf 'COLD_REQUEST_ID=%s\n' "$TASK_COLD_JSON_REQUEST_ID"
  printf 'COLD_STARTUP=%s\n' "$TASK_STARTUP_ROWS"
  printf 'cold-cycle=corroborated\n'
)
~~~

If a failure is captured, stop and design a separately reviewed mitigation
from its classification. If both corroborated cold requests return `200`,
record only `not reproduced in four total diagnostic calls`. Do not call the
behavior fixed. Remove the `provider-diag` tag through this separate
fail-closed finalization gate, which leaves the prior revision at 100% and the
service private:

~~~zsh
(
  set -euo pipefail

  TASK_FINAL_BEFORE="/tmp/spooky-final-before.json"
  TASK_FINAL_AFTER="/tmp/spooky-final-after.json"
  TASK_FINAL_POLICY="/tmp/spooky-final-policy.json"

  spooky_final_cleanup() {
    rm -f -- \
      "$TASK_FINAL_BEFORE" \
      "$TASK_FINAL_AFTER" \
      "$TASK_FINAL_POLICY"
  }

  spooky_final_verify_closed() {
    local verification_failed=0

    gcloud run services describe "$TASK_SERVICE" \
      --project "$TASK_PROJECT" \
      --region "$TASK_REGION" \
      --format=json > "$TASK_FINAL_AFTER" || verification_failed=1
    gcloud run services get-iam-policy "$TASK_SERVICE" \
      --project "$TASK_PROJECT" \
      --region "$TASK_REGION" \
      --format=json > "$TASK_FINAL_POLICY" || verification_failed=1

    jq -e --arg prior "$TASK_PRIOR_REVISION" \
      --arg diagnostic "$TASK_DIAG_REVISION" '
      any(.status.traffic[]?;
        .revisionName == $prior and (.percent // 0) == 100) and
      ([.status.traffic[]? | select(.tag == "provider-diag")] | length == 0) and
      ([.status.traffic[]? | select(.revisionName == $diagnostic)]
        | length == 0) and
      ((.metadata.annotations["run.googleapis.com/invoker-iam-disabled"]
        // "false") == "false")
    ' "$TASK_FINAL_AFTER" > /dev/null || verification_failed=1
    jq -e '
      [.bindings[]?.members[]?] | index("allUsers") == null
    ' "$TASK_FINAL_POLICY" > /dev/null || verification_failed=1

    return "$verification_failed"
  }

  spooky_final_recover() {
    local recovery_failed=0
    set +e

    gcloud run services update "$TASK_SERVICE" \
      --project "$TASK_PROJECT" \
      --region "$TASK_REGION" \
      --invoker-iam-check || recovery_failed=1
    gcloud run services update-traffic "$TASK_SERVICE" \
      --project "$TASK_PROJECT" \
      --region "$TASK_REGION" \
      --to-revisions "${TASK_PRIOR_REVISION}=100" || recovery_failed=1
    gcloud run services update-traffic "$TASK_SERVICE" \
      --project "$TASK_PROJECT" \
      --region "$TASK_REGION" \
      --remove-tags provider-diag || recovery_failed=1
    spooky_final_verify_closed || recovery_failed=1

    if (( recovery_failed == 0 )); then
      printf 'diagnostic-finalization-recovery=passed\n'
    else
      printf 'diagnostic-finalization-recovery=failed\n' >&2
    fi
    set -e
    return "$recovery_failed"
  }

  spooky_final_exit() {
    local exit_status="$?"
    trap - EXIT
    if (( exit_status != 0 )); then
      spooky_final_recover || true
    fi
    spooky_final_cleanup
    exit "$exit_status"
  }

  trap spooky_final_cleanup EXIT

  gcloud run services describe "$TASK_SERVICE" \
    --project "$TASK_PROJECT" \
    --region "$TASK_REGION" \
    --format=json > "$TASK_FINAL_BEFORE"
  gcloud run services get-iam-policy "$TASK_SERVICE" \
    --project "$TASK_PROJECT" \
    --region "$TASK_REGION" \
    --format=json > "$TASK_FINAL_POLICY"

  jq -e --arg prior "$TASK_PRIOR_REVISION" \
    --arg diagnostic "$TASK_DIAG_REVISION" '
    any(.status.traffic[]?;
      .revisionName == $prior and (.percent // 0) == 100) and
    any(.status.traffic[]?;
      .revisionName == $diagnostic and .tag == "provider-diag" and
      (.percent // 0) == 0) and
    ((.metadata.annotations["run.googleapis.com/invoker-iam-disabled"]
      // "false") == "false")
  ' "$TASK_FINAL_BEFORE" > /dev/null
  jq -e '
    [.bindings[]?.members[]?] | index("allUsers") == null
  ' "$TASK_FINAL_POLICY" > /dev/null

  trap spooky_final_exit EXIT

  gcloud run services update-traffic "$TASK_SERVICE" \
    --project "$TASK_PROJECT" \
    --region "$TASK_REGION" \
    --remove-tags provider-diag

  spooky_final_verify_closed
  printf 'diagnostic-finalization=passed\n'
)
~~~

Do not consider finalization complete unless the block exits zero and prints
`diagnostic-finalization=passed`. On a failure after mutation begins, its
`EXIT` trap preserves the original failure status while restoring the private
invoker check, prior revision at 100%, absent tag, and verified private state.
A later private release-candidate promotion requires a separate policy decision
that explicitly accepts the residual risk.

Bound the log query to the diagnostic revision and test timestamps. Project
only the allowlisted structured diagnostic fields; never fetch a complete log
payload:

~~~zsh
TASK_DIAG_FILTER="resource.type=\"cloud_run_revision\" AND \
resource.labels.service_name=\"${TASK_SERVICE}\" AND \
resource.labels.revision_name=\"${TASK_DIAG_REVISION}\" AND \
timestamp>=\"${TASK_DIAG_START}\" AND timestamp<=\"${TASK_DIAG_END}\" AND \
jsonPayload.event=\"spooky_provider_failure\""

gcloud logging read "$TASK_DIAG_FILTER" \
  --project "$TASK_PROJECT" \
  --limit 10 \
  --format='table(timestamp,resource.labels.revision_name,jsonPayload.request_id,jsonPayload.failure_source,jsonPayload.failure_category,jsonPayload.upstream_status)'
~~~

Correlate those rows with request metadata without projecting the request URL
or any payload:

~~~zsh
gcloud logging read \
  "resource.type=\"cloud_run_revision\" AND \
resource.labels.service_name=\"${TASK_SERVICE}\" AND \
resource.labels.revision_name=\"${TASK_DIAG_REVISION}\" AND \
timestamp>=\"${TASK_DIAG_START}\" AND timestamp<=\"${TASK_DIAG_END}\" AND \
httpRequest.requestUrl:\"/v1/chat\"" \
  --project "$TASK_PROJECT" \
  --limit 10 \
  --format='table(timestamp,resource.labels.revision_name,httpRequest.status,httpRequest.latency,trace)'
~~~

Stop after classification or after the bounded no-reproduction path. Do not
make the service public or move traffic until the failure category has been
reviewed and a separate mitigation has passed the private gate, or until a
separate policy decision explicitly accepts the residual risk.

## Open publicly only after private verification

After explicit approval, disable the invoker IAM check:

~~~zsh
gcloud run services update "$TASK_SERVICE" \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --no-invoker-iam-check
~~~

If an organization policy blocks this operation, stop and report it. Do not
weaken an organization policy broadly and do not fall back silently to another
public-access mechanism.

Repeat public health and chat requests without the Authorization header, then
execute the success-envelope, request-ID, and exact CORS assertions:

~~~zsh
(
  set -euo pipefail

  spooky_public_cleanup() {
    unset TASK_ID_TOKEN 2>/dev/null || true
    rm -f -- \
      /tmp/spooky-service.yaml \
      /tmp/spooky-public-health-headers.txt \
      /tmp/spooky-public-health.json \
      /tmp/spooky-public-chat-headers.txt \
      /tmp/spooky-public-chat.json \
      /tmp/spooky-public-preflight-headers.txt
  }
  trap spooky_public_cleanup EXIT

  TASK_PUBLIC_HEALTH_STATUS="$(curl --fail-with-body --silent --show-error \
    -H 'Origin: https://absurdwall.github.io' \
    -D /tmp/spooky-public-health-headers.txt \
    -o /tmp/spooky-public-health.json \
    -w '%{http_code}' \
    "$TASK_ENDPOINT/health")"

  TASK_PUBLIC_CHAT_STATUS="$(curl --fail-with-body --silent --show-error \
    -H 'Origin: https://absurdwall.github.io' \
    -H 'Content-Type: application/json' \
    -D /tmp/spooky-public-chat-headers.txt \
    -o /tmp/spooky-public-chat.json \
    -d '{"message":"What is the difference between a Tool and a Skill?"}' \
    -w '%{http_code}' \
    "$TASK_ENDPOINT/v1/chat")"

  TASK_PUBLIC_PREFLIGHT_STATUS="$(curl --fail-with-body --silent --show-error \
    -X OPTIONS \
    -H 'Origin: https://absurdwall.github.io' \
    -H 'Access-Control-Request-Method: POST' \
    -H 'Access-Control-Request-Headers: content-type' \
    -D /tmp/spooky-public-preflight-headers.txt \
    -o /dev/null \
    -w '%{http_code}' \
    "$TASK_ENDPOINT/v1/chat")"

  test "$TASK_PUBLIC_HEALTH_STATUS" = "200"
  test "$TASK_PUBLIC_CHAT_STATUS" = "200"
  test "$TASK_PUBLIC_PREFLIGHT_STATUS" = "200"
  jq -e '.status == "ok"' /tmp/spooky-public-health.json > /dev/null
  jq -e '
    (.answer | type == "string" and length > 0) and
    (.request_id | type == "string" and startswith("req_")) and
    any(.sources[]; .url | endswith("#tool")) and
    any(.sources[]; .url | endswith("#skill"))
  ' /tmp/spooky-public-chat.json > /dev/null

  TASK_PUBLIC_JSON_REQUEST_ID="$(jq -r '.request_id' \
    /tmp/spooky-public-chat.json)"
  TASK_PUBLIC_HEADER_REQUEST_ID="$(spooky_header_value \
    'X-Request-ID' /tmp/spooky-public-chat-headers.txt)"
  test "$TASK_PUBLIC_JSON_REQUEST_ID" = "$TASK_PUBLIC_HEADER_REQUEST_ID"

  test "$(spooky_header_value \
    'Access-Control-Allow-Origin' /tmp/spooky-public-health-headers.txt)" \
    = "https://absurdwall.github.io"
  test "$(spooky_header_value \
    'Access-Control-Allow-Origin' /tmp/spooky-public-chat-headers.txt)" \
    = "https://absurdwall.github.io"
  test "$(spooky_header_value \
    'Access-Control-Expose-Headers' /tmp/spooky-public-chat-headers.txt)" \
    = "X-Request-ID"
  test "$(spooky_header_value \
    'Access-Control-Allow-Origin' /tmp/spooky-public-preflight-headers.txt)" \
    = "https://absurdwall.github.io"
  test "$(spooky_header_value \
    'Access-Control-Allow-Methods' /tmp/spooky-public-preflight-headers.txt)" \
    = "GET, POST"
  test "$(spooky_header_value \
    'Access-Control-Allow-Headers' /tmp/spooky-public-preflight-headers.txt)" \
    = "Accept, Accept-Language, Content-Language, Content-Type"

  if grep -Eqi '^access-control-allow-credentials:' \
    /tmp/spooky-public-health-headers.txt \
    /tmp/spooky-public-chat-headers.txt \
    /tmp/spooky-public-preflight-headers.txt; then
    echo "Unexpected CORS credentials support" >&2
    exit 1
  fi

  printf 'public-verification=passed\n'
)
~~~

Do not record public verification as successful unless this fail-closed block
exits zero and prints `public-verification=passed`. The `EXIT` trap always
removes the temporary files and any token variable.

Record only the safe verification facts before the final cleanup command. The
header assertions require the exact public origin, exposed request-ID header,
documented methods, middleware's fixed safe header set, and no credentials
support.

## Safe logs, billing, and delivery record

Use Logs Explorer, or project only request metadata with Cloud Logging. Do not
use a command that returns unrestricted `textPayload`, `jsonPayload`, or
`protoPayload`, and do not record request/model bodies:

~~~zsh
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="spooky-api"' \
  --project "$TASK_PROJECT" \
  --limit 20 \
  --format='table(timestamp,severity,httpRequest.requestMethod,httpRequest.status,httpRequest.latency,resource.labels.revision_name,trace)'
~~~

Billing data can take hours to appear. In Billing Reports, filter to project
`search-agent-lab` and record the Cloud Run and Vertex AI service/SKU presence,
the trial-credit effect when visible, and the check time. Do not claim a zero
cost or credit application before the report contains the usage.

The final deployment record must contain:

- exact commit SHA, project, Cloud Run region, and model location;
- public HTTPS URL, ready revision, and image digest;
- setup/human, build, and runtime identities and their verified roles;
- environment-variable names, absence of credential/secret bindings, and all
  resource controls;
- deterministic test result plus private and public live-check facts;
- safe Logs Explorer location/query and billing-check status;
- budget amount/thresholds;
- redeploy, recovery, rollback, and teardown commands.

## Redeploy, recovery, rollback, and teardown

Redeploy only from another pushed, reviewed, detached full commit SHA. Repeat
the direct model check, private deployment, authenticated verification,
configuration audit, and explicit public-opening gate.

### First-revision failure

If the first revision fails, there is no previous revision to roll back to.
Restore private access first, then repair or delete the service:

~~~zsh
gcloud run services update "$TASK_SERVICE" \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --invoker-iam-check
~~~

### Roll back to a previously verified revision

Rollback is available only after a prior revision has been verified. First
restore the private invoker check, then shift traffic:

~~~zsh
gcloud run services update "$TASK_SERVICE" \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --invoker-iam-check

gcloud run services update-traffic "$TASK_SERVICE" \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --to-revisions "VERIFIED_PREVIOUS_REVISION=100"
~~~

While the service remains private, repeat the authenticated health and
Tool-versus-Skill chat checks plus the exported-configuration credential audit
from the private verification sections. Require all checks to pass. Only after
recording approval may the setup administrator run the
`--no-invoker-iam-check` public-opening command again.

### Return traffic to the latest ready revision

Returning to latest follows the same private-first gate:

~~~zsh
gcloud run services update "$TASK_SERVICE" \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --invoker-iam-check

gcloud run services update-traffic "$TASK_SERVICE" \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --to-latest
~~~

Repeat authenticated health/chat verification and the configuration audit
while private. Reopen with `--no-invoker-iam-check` only after explicit
approval.

### Complete teardown

First re-enable the invoker check. Before deleting, inventory the Cloud Run
service/revisions, Artifact Registry repository/images, Cloud Build history,
Cloud Storage source-staging objects or buckets, task IAM bindings, runtime
service account, enabled APIs, and project-scoped budget alert. Record whether
each artifact will be deleted, left to provider retention, or intentionally
retained.

Then remove task-owned resources in this order:

1. Delete Cloud Run service `spooky-api`.
2. Delete images/repository `cloud-run-source-deploy` in `us-east1`, or retain
   it only with an explicit Artifact Registry cleanup policy.
3. Remove task-created source-staging objects/buckets only after confirming no
   other workload uses them. Cloud Build history/logs that cannot or should not
   be deleted follow the provider retention policy; record that retention.
4. Remove `roles/run.builder` from the Compute Engine default build identity
   only if this task added the binding and no other workload needs it. Do not
   delete the default Compute Engine service account.
5. Remove role bindings from and delete `spooky-api-runtime` after the service
   no longer references it.
6. Remove task-specific deployer, build-actAs, smoke-caller, and service-scoped
   Invoker bindings that are no longer needed.
7. Delete the project budget alert if it was created only for this service, or
   explicitly record that it remains for other project usage.
8. Optionally disable the enabled APIs only after their resources are gone and
   no other project workload uses them.

Service-only deletion is:

~~~zsh
gcloud run services delete "$TASK_SERVICE" \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION"
~~~

Review every target before deletion. Project deletion is a separate,
destructive recovery path and is not part of this runbook.
