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
