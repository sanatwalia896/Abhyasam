# Abhyasam Deployment Runbook

This guide explains how to deploy Abhyasam without local Docker publishing or long-lived Google service-account keys.

## Architecture

~~~text
GitHub Actions
  -> runs tests
  -> builds a Linux AMD64 Docker image
  -> pushes it to Artifact Registry
  -> deploys the backend to Cloud Run

Vercel
  -> builds the static frontend
  -> injects the Cloud Run URL
  -> publishes the frontend at https://abhyasam.vercel.app
~~~

The frontend and backend are separate deployments. API keys stay in Google Secret Manager. The browser receives only the public backend URL.

## 1. Current staging values

~~~text
Google Cloud project:       abhyasam
Project number:             333411347599
Region:                     us-central1
Artifact Registry repo:     abhyasam-backend
Cloud Run service:          abhyasam-backend-staging
GitHub branch:              cloud-run-migration
Frontend domain:            https://abhyasam.vercel.app
~~~

Always get the current Cloud Run URL instead of copying an old URL:

~~~bash
gcloud run services describe abhyasam-backend-staging \
  --project=abhyasam \
  --region=us-central1 \
  --format='value(status.url)'
~~~

## 2. Authenticate and enable Google Cloud APIs

~~~bash
gcloud auth login
gcloud config set project abhyasam
gcloud auth list
gcloud config get-value project
~~~

The active account must have project IAM permissions.

Enable the required APIs once:

~~~bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  storage.googleapis.com \
  --project=abhyasam
~~~

These APIs provide Cloud Run, image storage, secrets, GitHub federation, token exchange, and Cloud Storage.

## 3. Service accounts

Use separate service accounts:

| Account | Used by | Purpose |
|---|---|---|
| abhyasam-deployer@abhyasam.iam.gserviceaccount.com | GitHub Actions | Push images and deploy Cloud Run |
| abhyasam-runtime@abhyasam.iam.gserviceaccount.com | Cloud Run | Read secrets and application data |

Create them only if they do not exist:

~~~bash
gcloud iam service-accounts create abhyasam-deployer \
  --project=abhyasam \
  --display-name='Abhyasam GitHub deployer'

gcloud iam service-accounts create abhyasam-runtime \
  --project=abhyasam \
  --display-name='Abhyasam Cloud Run runtime'
~~~

Why two accounts? GitHub needs deployment privileges, while the running application should receive only runtime privileges.

Never create or commit a service-account JSON key. GitHub uses Workload Identity Federation.

## 4. Artifact Registry

The repository name is abhyasam-backend. It is not the project ID.

Create it if necessary:

~~~bash
gcloud artifacts repositories create abhyasam-backend \
  --project=abhyasam \
  --location=us-central1 \
  --repository-format=docker \
  --description='Abhyasam backend container images'
~~~

Allow the deployer to push images:

~~~bash
gcloud artifacts repositories add-iam-policy-binding abhyasam-backend \
  --project=abhyasam \
  --location=us-central1 \
  --member='serviceAccount:abhyasam-deployer@abhyasam.iam.gserviceaccount.com' \
  --role='roles/artifactregistry.writer'
~~~

## 5. Secret Manager

Create these exact secret names:

~~~text
groq-api-key
pinecone-api-key
notion-token
~~~

Using the Cloud Console:

1. Open Secret Manager and choose Create secret.
2. Use the exact lower-case hyphenated name.
3. Add the value as the first version.
4. Google-managed encryption is sufficient.
5. Automatic replication is simplest. Manual us-central1 replication also works.
6. Do not set an expiration date unless intentional.

For CLI creation, never put a real key into this guide:

~~~bash
printf '%s' 'REPLACE_WITH_REAL_VALUE' | gcloud secrets create groq-api-key \
  --project=abhyasam --data-file=-
~~~

Rotate a value by adding a new version:

~~~bash
printf '%s' 'REPLACE_WITH_NEW_VALUE' | gcloud secrets versions add groq-api-key \
  --project=abhyasam --data-file=-
~~~

Allow the Cloud Run runtime account to read the secrets:

~~~bash
for SECRET in groq-api-key pinecone-api-key notion-token; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --project=abhyasam \
    --member='serviceAccount:abhyasam-runtime@abhyasam.iam.gserviceaccount.com' \
    --role='roles/secretmanager.secretAccessor'
done
~~~

Why Secret Manager? The keys are encrypted and are injected into Cloud Run at runtime. They are not stored in GitHub or inside the Docker image.

## 6. Cloud Storage permissions

Give the runtime account access to the application bucket:

~~~bash
gcloud storage buckets add-iam-policy-binding gs://abhyasam-1234 \
  --member='serviceAccount:abhyasam-runtime@abhyasam.iam.gserviceaccount.com' \
  --role='roles/storage.objectUser'
~~~

The GitHub variable GCS_BUCKET_NAME must contain only:

~~~text
abhyasam-1234
~~~

## 7. Workload Identity Federation

Workload Identity Federation lets GitHub Actions exchange its short-lived GitHub OIDC identity for temporary Google credentials. This avoids a permanent Google key in GitHub.

Create the pool once:

~~~bash
gcloud iam workload-identity-pools create github \
  --project=abhyasam \
  --location=global \
  --display-name='GitHub Actions'
~~~

Create the staging OIDC provider once:

~~~bash
gcloud iam workload-identity-pools providers create-oidc github-provider-staging \
  --project=abhyasam \
  --location=global \
  --workload-identity-pool=github \
  --display-name='GitHub Actions staging provider' \
  --issuer-uri='https://token.actions.githubusercontent.com/' \
  --attribute-mapping='google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.repository_owner=assertion.repository_owner' \
  --attribute-condition="assertion.repository == 'sanatwalia896/Abhyasam' && assertion.ref == 'refs/heads/cloud-run-migration'"
~~~

Check them:

~~~bash
gcloud iam workload-identity-pools list \
  --project=abhyasam --location=global

gcloud iam workload-identity-pools providers list \
  --project=abhyasam \
  --location=global \
  --workload-identity-pool=github
~~~

Allow this repository to impersonate the deployer:

~~~bash
gcloud iam service-accounts add-iam-policy-binding \
  abhyasam-deployer@abhyasam.iam.gserviceaccount.com \
  --project=abhyasam \
  --role=roles/iam.workloadIdentityUser \
  --member='principalSet://iam.googleapis.com/projects/333411347599/locations/global/workloadIdentityPools/github/attribute.repository/sanatwalia896/Abhyasam'
~~~

The GitHub variable WIF_PROVIDER must be exactly:

~~~text
projects/333411347599/locations/global/workloadIdentityPools/github/providers/github-provider-staging
~~~

An invalid_target error normally means the provider path is wrong, missing, disabled, or in the wrong project.

## 8. Deployer IAM permissions

~~~bash
gcloud projects add-iam-policy-binding abhyasam \
  --member='serviceAccount:abhyasam-deployer@abhyasam.iam.gserviceaccount.com' \
  --role='roles/run.admin'

gcloud iam service-accounts add-iam-policy-binding \
  abhyasam-runtime@abhyasam.iam.gserviceaccount.com \
  --project=abhyasam \
  --member='serviceAccount:abhyasam-deployer@abhyasam.iam.gserviceaccount.com' \
  --role='roles/iam.serviceAccountUser'
~~~

The deployer can administer Cloud Run and attach the runtime account. The runtime account itself does not need deployment permissions.

## 9. GitHub Actions variables

The workflow is:

~~~text
.github/workflows/deploy-backend-staging.yml
~~~

In GitHub, open Settings → Environments → staging. Add these as Variables, not Secrets:

| Name | Value |
|---|---|
| GCP_PROJECT_ID | abhyasam |
| GCP_REGION | us-central1 |
| ARTIFACT_REPOSITORY | abhyasam-backend |
| CLOUD_RUN_SERVICE | abhyasam-backend-staging |
| RUNTIME_SERVICE_ACCOUNT | abhyasam-runtime@abhyasam.iam.gserviceaccount.com |
| DEPLOY_SERVICE_ACCOUNT | abhyasam-deployer@abhyasam.iam.gserviceaccount.com |
| WIF_PROVIDER | projects/333411347599/locations/global/workloadIdentityPools/github/providers/github-provider-staging |
| GCS_BUCKET_NAME | abhyasam-1234 |
| PINECONE_INDEX_NAME | abhyasam-fastembed-index |
| PINECONE_NAMESPACE | notion-knowledge |
| GROQ_MODEL | openai/gpt-oss-20b |
| VERCEL_ORIGIN | https://abhyasam.vercel.app |

Do not add GROQ_API_KEY, PINECONE_API_KEY, or NOTION_TOKEN to GitHub. The workflow reads them from Google Secret Manager.

## 10. What the backend workflow does

The workflow:

1. Checks out the selected commit.
2. Installs dependencies and runs backend tests.
3. Builds a Linux AMD64 Docker image on GitHub.
4. Bakes and verifies the FastEmbed model.
5. Authenticates through Workload Identity Federation.
6. Pushes the image to Artifact Registry.
7. Deploys Cloud Run using the runtime account.
8. Injects Secret Manager references.
9. Checks the health and MCQ endpoints.

The Docker base image is python:3.12-slim, a Linux Debian-based image. The workflow explicitly uses --platform linux/amd64 for Cloud Run compatibility.

The workflow automatically runs on pushes to cloud-run-migration only when backend paths change. Frontend-only changes do not trigger it. Run manually from GitHub Actions → Deploy backend to Cloud Run staging → Run workflow → cloud-run-migration.

## 11. Backend verification

~~~bash
SERVICE_URL=$(gcloud run services describe abhyasam-backend-staging \
  --project=abhyasam \
  --region=us-central1 \
  --format='value(status.url)')
echo "$SERVICE_URL"

curl -i "$SERVICE_URL/api/health"

curl -i \
  -H 'Origin: https://abhyasam.vercel.app' \
  "$SERVICE_URL/api/notion-pages"
~~~

Health should return:

~~~json
{"status":"ok","api_version":"3.0.0"}
~~~

The pages request should return JSON and include an access-control-allow-origin header for the Vercel domain.

If CORS needs a manual correction:

~~~bash
gcloud run services update abhyasam-backend-staging \
  --project=abhyasam \
  --region=us-central1 \
  --update-env-vars='CORS_ORIGINS=https://abhyasam.vercel.app'
~~~

## 12. Vercel configuration

Repository layout:

~~~text
Abhyasam/
├── frontend/
├── backend/
├── scripts/build-frontend.mjs
└── vercel.json
~~~

Vercel Root Directory must be the repository root, not frontend.

Vercel settings:

~~~text
Root Directory:   repository root / .
Build Command:    node scripts/build-frontend.mjs
Output Directory: frontend
Framework:        Other / none
~~~

Add this Vercel variable for Production:

~~~text
Key:         PUBLIC_API_BASE_URL
Value:       current Cloud Run service URL
Environment: Production
Type:        Config
~~~

Example:

~~~text
PUBLIC_API_BASE_URL=https://abhyasam-backend-staging-333411347599.us-central1.run.app
~~~

This is public browser configuration, so it is not a secret. API keys must never be added to Vercel frontend variables.

The build script writes the URL into frontend/js/deployment-config.js. After deployment, verify:

~~~text
https://abhyasam.vercel.app/js/deployment-config.js
~~~

It should contain the current Cloud Run URL. A 404 means the old Vercel deployment is live or the Vercel root directory is wrong.

## 13. Publish to the existing domain

Keep the branch named cloud-run-migration; do not rename it to main.

In Vercel:

1. Set Production Branch to cloud-run-migration.
2. Save PUBLIC_API_BASE_URL for Production.
3. Deploy the latest commit from cloud-run-migration.
4. Confirm the build succeeds.
5. Promote the successful deployment to Production.
6. Confirm the deployment is assigned to abhyasam.vercel.app.

The domain belongs to the Vercel project, not to a Git branch. Changing the production branch keeps the same domain.

Environment variables are applied at build time. Changing PUBLIC_API_BASE_URL requires a new Vercel deployment.

## 14. Normal release process

For a backend change:

1. Run tests locally.
2. Push to cloud-run-migration.
3. Wait for GitHub Actions.
4. Check the Cloud Run health endpoint.
5. Check CORS and API responses.
6. Update Vercel's API URL if the service URL changed.
7. Redeploy Vercel if necessary.
8. Test the live domain.

For a frontend-only change:

1. Push to cloud-run-migration.
2. Let Vercel build and deploy.
3. Do not expect the backend GitHub workflow to run; its path filter excludes frontend-only changes.
4. Test the live domain.

## 15. Troubleshooting

### WIF invalid_target

List providers and compare the exact provider name with WIF_PROVIDER:

~~~bash
gcloud iam workload-identity-pools providers list \
  --project=abhyasam \
  --location=global \
  --workload-identity-pool=github
~~~

### Artifact Registry permission denied

The repository argument must be abhyasam-backend, not abhyasam:

~~~bash
gcloud artifacts repositories describe abhyasam-backend \
  --project=abhyasam --location=us-central1
~~~

### Vercel cannot find frontend/scripts/build-frontend.mjs

The Vercel Root Directory is set to frontend. Set it to the repository root. Do not move the script.

### Frontend shows Unexpected token T

The browser received a plain-text error page instead of JSON. Check:

1. PUBLIC_API_BASE_URL is the current Cloud Run URL.
2. A new Vercel deployment was created after changing it.
3. The deployment was promoted to abhyasam.vercel.app.
4. The backend route works with curl.
5. CORS allows https://abhyasam.vercel.app.

### deployment-config.js returns 404

The old deployment is still serving production, or Vercel is using the wrong root directory. Deploy the latest branch with the repository root as Root Directory.

### Backend has secret or 403 errors

Verify that the runtime account has roles/secretmanager.secretAccessor and roles/storage.objectUser. Also verify the exact secret names and version 1.

### Backend workflow did not run after a frontend change

This is expected because of the workflow paths filter. Run it manually only if a backend deployment is needed.

## 16. Rollback

List Cloud Run revisions:

~~~bash
gcloud run revisions list \
  --service=abhyasam-backend-staging \
  --project=abhyasam \
  --region=us-central1
~~~

Use the Cloud Run Console to route traffic to a previous healthy revision.

For the frontend, open a previous successful Vercel deployment and choose Promote to Production.

## 17. Security rules

- Never commit .env files, API keys, service-account JSON files, or private keys.
- Keep API keys in Google Secret Manager.
- Keep PUBLIC_API_BASE_URL public because browsers need it.
- Use Workload Identity Federation instead of long-lived GitHub keys.
- Restrict WIF conditions to the exact repository and staging branch.
- Use separate staging and production services, buckets, secrets, and GitHub environments.
- Check the active Google account and project before IAM commands.

