# Cloud Run backend + Vercel frontend

The root Dockerfile builds ONLY `backend/`, installs its dependencies, downloads
BAAI/bge-small-en-v1.5 into `/opt/fastembed`, and verifies a 384-dimensional
embedding. Runtime uses `FASTEMBED_LOCAL_FILES_ONLY=true` and `HF_HUB_OFFLINE=1`.
GitHub Actions also tests the model with the container network disabled.
No `.env`, data files, frontend, or credential keys are copied into the image.
The container listens on `0.0.0.0:$PORT` (8080 by default).

Architecture:

    Vercel static frontend → HTTPS Cloud Run FastAPI → Groq / Pinecone
                                              └──→ private GCS bucket

Quiz sets, flashcard decks, chat histories and short-answer sessions are stored
in GCS. The browser never receives GCP credentials. Every browser tab gets its
own random session IDs. Requests within one practice session should remain
sequential; the UI disables submission while a request is pending.
The app supports up to 10 MCQ sets and 10 flashcard decks independently. The
private `system/locks/` objects are short-lived coordination leases used for
creation limits across Cloud Run instances; they use the same bucket permissions.
Clear unwanted decks through the flashcard library rather than auto-evicting them.
The DELETE API calls now empty their JSON and reuse the same object names. Empty
slots do not count against the ten-set/deck limit. Quiz revisions prevent stale
submissions after a slot is reused. GCS soft delete can retain overwritten object
generations too, so this behavior alone does not eliminate retention charges.

## 1. Choose your deployment settings

Run the one-time setup in a terminal with `gcloud` installed and authenticated.
Replace these values; the project ID is NOT the display name. This guide assumes
your backend branch is `main`. Change the workflow trigger and WIF branch condition
together if it has another name. No infrastructure is created by editing this file.

```bash
GCP_PROJECT=your-project-id
GCP_REGION=us-central1
GITHUB_REPO=sanatwalia896/Abhyasam
BACKEND_BRANCH=main
gcloud config set project "$GCP_PROJECT"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com secretmanager.googleapis.com
gcloud artifacts repositories create abhyasam --repository-format=docker --location="$GCP_REGION"
gcloud iam service-accounts create abhyasam-runtime --display-name="Abhyasam Cloud Run runtime"
gcloud iam service-accounts create abhyasam-deployer --display-name="Abhyasam GitHub deployer"
```

If a named resource already exists, use it rather than re-creating it.

## 2. Give the container access to the existing private bucket

```bash
gcloud storage buckets add-iam-policy-binding gs://abhyasam-1234 \
  --member="serviceAccount:abhyasam-runtime@$GCP_PROJECT.iam.gserviceaccount.com" \
  --role=roles/storage.objectUser
```

This grants object read/list/create/update/delete access on this bucket, which
the API needs for quizzes, sync state, decks, and sessions. It does not make the
bucket public. If the bucket belongs to another project, an administrator of
that bucket must grant this exact runtime identity access there.

At deployment, attach `abhyasam-runtime@PROJECT_ID.iam.gserviceaccount.com` to
Cloud Run. `storage.Client(project=...)` automatically uses its service identity
through Application Default Credentials. DO NOT set `GOOGLE_APPLICATION_CREDENTIALS`
in Cloud Run and do not mount/upload a service-account key.

References: [Cloud Run service identity](https://docs.cloud.google.com/run/docs/securing/service-identity),
[Storage IAM roles](https://docs.cloud.google.com/iam/docs/roles-permissions/storage).

## 3. Store API keys in Secret Manager

Create these three secrets:

```bash
gcloud secrets create groq-api-key --replication-policy=automatic
gcloud secrets create pinecone-api-key --replication-policy=automatic
gcloud secrets create notion-token --replication-policy=automatic
```

Use the Google Cloud console → Secret Manager → each secret → New version to
paste the corresponding value. Do not put secret values in workflow YAML or
Docker build arguments. Grant the runtime account access to each secret:

```bash
gcloud secrets add-iam-policy-binding groq-api-key --member="serviceAccount:abhyasam-runtime@$GCP_PROJECT.iam.gserviceaccount.com" --role=roles/secretmanager.secretAccessor
gcloud secrets add-iam-policy-binding pinecone-api-key --member="serviceAccount:abhyasam-runtime@$GCP_PROJECT.iam.gserviceaccount.com" --role=roles/secretmanager.secretAccessor
gcloud secrets add-iam-policy-binding notion-token --member="serviceAccount:abhyasam-runtime@$GCP_PROJECT.iam.gserviceaccount.com" --role=roles/secretmanager.secretAccessor
```

## 4. Authorize GitHub deployments without a JSON key

Grant the deployer permission to push images, deploy Cloud Run and attach the
runtime account. The deployer and runtime service accounts serve different purposes.

```bash
gcloud artifacts repositories add-iam-policy-binding abhyasam --location="$GCP_REGION" --member="serviceAccount:abhyasam-deployer@$GCP_PROJECT.iam.gserviceaccount.com" --role=roles/artifactregistry.writer
gcloud projects add-iam-policy-binding "$GCP_PROJECT" --member="serviceAccount:abhyasam-deployer@$GCP_PROJECT.iam.gserviceaccount.com" --role=roles/run.admin
gcloud iam service-accounts add-iam-policy-binding "abhyasam-runtime@$GCP_PROJECT.iam.gserviceaccount.com" --member="serviceAccount:abhyasam-deployer@$GCP_PROJECT.iam.gserviceaccount.com" --role=roles/iam.serviceAccountUser
gcloud iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global --workload-identity-pool=github \
  --issuer-uri=https://token.actions.githubusercontent.com \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '$GITHUB_REPO' && assertion.ref == 'refs/heads/$BACKEND_BRANCH'"
GCP_PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)')
gcloud iam service-accounts add-iam-policy-binding "abhyasam-deployer@$GCP_PROJECT.iam.gserviceaccount.com" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$GCP_PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GITHUB_REPO"
```

Reference: [GitHub authentication action and WIF setup](https://github.com/google-github-actions/auth).

## 5. Configure GitHub Actions

Create a GitHub environment called `production`. Under its Variables, add:

| Variable | Example/value |
|---|---|
| `GCP_PROJECT_ID` | Your actual project ID |
| `GCP_REGION` | `us-central1` |
| `ARTIFACT_REPOSITORY` | `abhyasam` |
| `CLOUD_RUN_SERVICE` | `abhyasam-backend` |
| `RUNTIME_SERVICE_ACCOUNT` | `abhyasam-runtime@PROJECT_ID.iam.gserviceaccount.com` |
| `DEPLOY_SERVICE_ACCOUNT` | `abhyasam-deployer@PROJECT_ID.iam.gserviceaccount.com` |
| `WIF_PROVIDER` | `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github-provider` |
| `PINECONE_INDEX_NAME` | Your already populated 384-dimensional index |
| `VERCEL_ORIGIN` | `https://your-app.vercel.app` (no path or trailing slash) |

`VERCEL_ORIGIN` may contain comma-separated exact origins when using both a
custom domain and a Vercel domain. Preview deployments need their own allowed
origins; don't assume they match the production hostname.

Commit `.github/workflows/deploy-backend.yml` and the backend/image changes to
the backend branch. The workflow tests the API, builds an AMD64 image, verifies
offline embedding, pushes to Artifact Registry, deploys, and checks API and GCS
listing. You can also run it from Actions → Deploy backend to Cloud Run → Run workflow.

The workflow initially uses 2 CPU, 2 GiB RAM, concurrency 4, max 1 instance,
and a 900-second request timeout. Tune these after measuring workload and cost.
The application shares a rolling Groq budget within one process (default 20 RPM /
8,000 TPM), accounts for actual response token usage, and respects Retry-After
with bounded retries. Calls run immediately while budget remains; fixed spacing
between successful calls is not used. Set
`GROQ_REQUESTS_PER_MINUTE` and `GROQ_TOKENS_PER_MINUTE` to match the limits shown
in YOUR Groq organization. Higher Cloud Run instance counts require a distributed
limiter or partitioned budgets; other applications using the same Groq organization
also consume the quota. A long/daily quota exhaustion is returned as HTTP 429
instead of holding the request open indefinitely. Rollouts can temporarily overlap
instances, so a one-instance setting is not an organization-wide quota guarantee.
Public browser access is enabled with `--allow-unauthenticated`; this app currently
has no login/authorization layer, so anyone knowing the URL can call its APIs.
CORS controls browser origins, not API authorization. Add application authentication
before sharing a deployment that must restrict generation/deletion to you.

Reference: [Cloud Run deploy action](https://github.com/google-github-actions/deploy-cloudrun).

## 6. Update the frontend branch on Vercel

Bring the updated `frontend/` and `scripts/build-frontend.mjs` into your frontend
branch. Do not merge the backend deployment workflow if that branch is frontend-only.

On that branch replace the ROOT `vercel.json` with the contents of
`deploy/vercel.frontend.json`. The old root config routes requests to Python and
must not be used for a static frontend. The supplied config assumes Vercel's
Root Directory is the repository root. It runs:

```text
Build command: node scripts/build-frontend.mjs
Output directory: frontend
Framework preset: Other
```

In Vercel Environment Variables set:

```text
PUBLIC_API_BASE_URL=https://YOUR-CLOUD-RUN-SERVICE-URL
```

Redeploy the frontend. Static browser JavaScript cannot read Vercel environment
variables directly; the build script writes this public URL into
`frontend/js/deployment-config.js`, loaded before the shared API configuration
on every page. Do not put Groq, Pinecone, Notion, or GCS secrets in Vercel's
frontend variables. Keep the Cloud Run URL separate from `CORS_ORIGINS`, which
contains the FRONTEND URL. Use HTTPS on both sides.

## 7. Verify

```bash
curl https://YOUR-CLOUD-RUN-URL/api/health
curl https://YOUR-CLOUD-RUN-URL/api/runtime-info
curl https://YOUR-CLOUD-RUN-URL/api/notion-pages
curl https://YOUR-CLOUD-RUN-URL/api/mcq/sets
```

Open the Vercel site. Check Network requests use the Cloud Run HTTPS URL, not
localhost or the Vercel domain. Generate a quiz and verify its JSON in
`gs://abhyasam-1234/quiz/question_sets/`. Generate flashcards for a specific page;
their JSON appears under `flashcards/decks/`. Refreshing a URL containing a deck ID
reloads that exact deck from GCS. Chat/practice state is under `sessions/` so
subsequent requests can reach another container instance.

Troubleshooting:

- GCS 403: check the runtime service identity and bucket role, not GitHub's identity.
- Secrets startup failure: check the runtime account's Secret Accessor role and secret versions.
- Browser CORS failure: compare the exact Vercel origin with `CORS_ORIGINS`.
- Offline model failure: rebuild the image; both download and offline verification must pass.
- Build on Apple Silicon locally: use `docker build --platform linux/amd64 -t abhyasam-backend .` for Cloud Run.

Container filesystems and in-memory state are not reliable persistence across
Cloud Run instances. [Google's session-affinity documentation](https://docs.cloud.google.com/run/docs/configuring/session-affinity)
explains why instance affinity does not replace external session storage.

The container is backend-only. For local UI testing, run `python3 -m uvicorn
main:app --reload` from `backend/` and open http://localhost:8000/index.html.
The local checkout still serves static files; the production image sets
`SERVE_FRONTEND=false` and excludes them.
