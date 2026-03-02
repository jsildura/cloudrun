#!/bin/bash
# deploy.sh
# Deploys Gamdl to Google Cloud Run (Backend + Wrapper)

PROJECT_ID="amdlxd-serverless"
REGION="asia-southeast1" # You can change this to us-central1 or another region close to you
SERVICE_NAME="gamdl-serverless"

echo "============================================"
echo "  Deploying Gamdl to Cloud Run"
echo "  Project: $PROJECT_ID"
echo "  Region:  $REGION"
echo "============================================"

# 1. Ensure gcloud is set to the correct project
gcloud config set project $PROJECT_ID

# 2. Enable APIs (Billing required here)
echo "Enabling APIS..."
gcloud services enable run.googleapis.com artifactregistry.googleapis.com

# 3. Create Artifact Registry repository if it doesn't exist
echo "Setting up Artifact Registry..."
gcloud artifacts repositories create gamdl-repo \
    --repository-format=docker \
    --location=$REGION \
    --description="Gamdl Docker repository" || true

# 4. Authenticate Docker to Artifact Registry
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# 5. Build and Push Wrapper Image
WRAPPER_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/gamdl-repo/gamdl-wrapper:latest"
echo "Building Wrapper image..."
cd Wrapper
docker build -t $WRAPPER_IMAGE .
docker push $WRAPPER_IMAGE
cd ..

# 6. Build and Push Gamdl API Image
API_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/gamdl-repo/gamdl-api:latest"
echo "Building Gamdl API image..."
docker build -t $API_IMAGE .
docker push $API_IMAGE

# 7. Update cloudrun.yaml with the new image tags
echo "Updating cloudrun.yaml with new image tags..."
# Replace the gamdl-api image placeholder
sed -i "s|image: gcr.io/PROJECT_ID/gamdl-api|image: $API_IMAGE|" cloudrun.yaml
# Replace the gamdl-wrapper image placeholder 
sed -i "s|image: gcr.io/PROJECT_ID/gamdl-wrapper|image: $WRAPPER_IMAGE|" cloudrun.yaml

# 8. Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run services replace cloudrun.yaml --region $REGION

# 9. Make the API public (Cloud Run gen2 uses IAM policy binding on the service)
echo "Making service public..."
gcloud run services add-iam-policy-binding $SERVICE_NAME \
    --region=$REGION \
    --member="allUsers" \
    --role="roles/run.invoker"

echo "============================================"
echo "Deployment Complete!"
echo "Check your Cloud Run dashboard for the API URL."
echo "Put that URL into your Cloudflare Pages build config (API_URL variable)."
echo "============================================"
