# Spooky Cloud Run deployment

This runbook deploys only the single-turn FastAPI service in
`search_agent_lab/spooky_api.py`. It does not deploy ADK Web or expose ADK
sessions, events, traces, tool payloads, exceptions, credentials, or OpenAPI
documentation.

## Deployment contract

| Setting | Value |
| --- | --- |
| Service | `spooky-api` |
| Region | Confirm in Google Cloud Console before creating resources |
| Access | Public HTTPS; Cloud Run invoker IAM check disabled |
| Billing | Request-based |
| Instances | Minimum `0`; service maximum `2` |
| Concurrency | `1` request per instance |
| Request timeout | `180s` |
| Resources | `1` CPU; `512Mi` memory |
| Runtime identity | `spooky-api-runtime` dedicated service account |
| Secret | `GOOGLE_API_KEY` from pinned Secret Manager version `1` |
| Default CORS | Two documented localhost origins plus `https://absurdwall.github.io` |

Concurrency is intentionally one because the process shares one ADK Runner and
one in-memory session service, while each request can wait on several serial
model turns. The service maximum of two bounds normal parallel provider calls
without pretending to be a hard spending cap. Cloud Run compute charges and
Gemini API charges remain separate.

## Browser checkpoints

Perform one checkpoint at a time in Google Cloud Console and verify the visible
result before continuing. Enter the Gemini key only in Secret Manager; never
put it in source code, Cloud Shell commands, browser requests, screenshots, or
chat messages.

1. Select or create the project, link its intended billing account, and confirm
   the region. Do not create service resources yet.
2. Enable only Cloud Run Admin API, Cloud Build API, Artifact Registry API,
   Secret Manager API, and IAM API if it is not already enabled.
3. Create the `spooky-gemini-api-key` secret with automatic replication. Paste
   the existing Gemini key directly into the Console as version `1`.
4. Create the `spooky-api-runtime` service account. On the secret itself, grant
   that service account only `Secret Manager Secret Accessor`. Do not grant the
   runtime identity project-wide editor or owner access.
5. Review the deployment settings above, then explicitly approve the source
   build and public deployment.

Google's current references are the
[source deployment guide](https://cloud.google.com/run/docs/deploying-source-code),
[secret binding guide](https://cloud.google.com/run/docs/configuring/services/secrets),
and [public access guide](https://cloud.google.com/run/docs/authenticating/public).

## Deploy or redeploy from Cloud Shell

The feature branch must be pushed before using these commands. Open Cloud Shell
inside the selected project, clone the public repository, and check out the
deployment branch. Set `TASK_REGION` to the region already confirmed in the
Console.

~~~zsh
git clone https://github.com/absurdwall/search-agent-lab.git
cd search-agent-lab
git switch codex/spooky-cloud-run

TASK_REGION="CONFIRMED_REGION"
TASK_PROJECT="$(gcloud config get-value project)"

gcloud run deploy spooky-api \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --source . \
  --service-account "spooky-api-runtime@${TASK_PROJECT}.iam.gserviceaccount.com" \
  --set-secrets "GOOGLE_API_KEY=spooky-gemini-api-key:1" \
  --port 8080 \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 1 \
  --timeout 180s \
  --cpu-throttling \
  --min 0 \
  --max 2 \
  --ingress all \
  --no-invoker-iam-check
~~~

Source deployment uses the checked-in `Dockerfile`; `.gcloudignore` prevents
local credentials and non-runtime materials from entering the uploaded source,
and `.dockerignore` keeps them out of the image build context. Source deployment
may create the `cloud-run-source-deploy` Artifact Registry repository when the
project does not already have one in the selected region.

## Verification record

Record the values reported by Cloud Run after deployment:

- project and region;
- public HTTPS URL;
- latest ready revision;
- image digest;
- request-based billing, min `0`, max `2`, concurrency `1`, and timeout `180s`;
- runtime service account and the name plus pinned version of the secret;
- controlled `/health` and `/v1/chat` status, response envelope, and
  `X-Request-ID` without recording learner content or model text.

Use one health request and one controlled real question:

~~~zsh
TASK_ENDPOINT="$(gcloud run services describe spooky-api \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --format='value(status.url)')"

curl --fail-with-body --silent --show-error \
  -H 'Origin: https://absurdwall.github.io' \
  -D /tmp/spooky-health-headers.txt \
  "$TASK_ENDPOINT/health"

curl --fail-with-body --silent --show-error \
  -H 'Origin: https://absurdwall.github.io' \
  -H 'Content-Type: application/json' \
  -D /tmp/spooky-chat-headers.txt \
  -d '{"message":"What is the difference between a Tool and a Skill?"}' \
  "$TASK_ENDPOINT/v1/chat"
~~~

Cloud Run request, container, and system logs are available under the service's
**Logs** tab or with the following metadata-only read. Do not copy model output,
request bodies, provider bodies, or secret values into the deployment record.

~~~zsh
gcloud run services logs read spooky-api \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --limit 20
~~~

## Rollback and teardown

To roll traffic back, first select a previously verified revision in the Cloud
Run **Revisions** tab. The equivalent Cloud Shell command is:

~~~zsh
gcloud run services update-traffic spooky-api \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION" \
  --to-revisions "VERIFIED_PREVIOUS_REVISION=100"
~~~

Deleting the service is separate from deleting its secret, runtime service
account, or Artifact Registry images. Review each target in the Console before
removal. The service-only teardown command is:

~~~zsh
gcloud run services delete spooky-api \
  --project "$TASK_PROJECT" \
  --region "$TASK_REGION"
~~~

Budget alerts are useful notifications, but they are not a hard spending cap.
The low service maximum and concurrency reduce burst exposure; they do not stop
an attacker from making serial public requests over time.
