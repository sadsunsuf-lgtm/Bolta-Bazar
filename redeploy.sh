#!/bin/bash
# ============================================================
# Bolta Bazaar — Redeploy Script (Google Cloud Shell)
# Run this in Cloud Shell to push all fixes to production
# ============================================================

set -e  # Stop on any error

# ---- CONFIG — Edit these if needed ----
PROJECT_ID="bolta-bazaar"
REGION="asia-south1"
BACKEND_SERVICE="bolta-bazaar-backend"
FRONTEND_SERVICE="bolta-bazaar-frontend"
BACKEND_IMAGE="gcr.io/${PROJECT_ID}/${BACKEND_SERVICE}"
FRONTEND_IMAGE="gcr.io/${PROJECT_ID}/${FRONTEND_SERVICE}"
BACKEND_URL="https://${BACKEND_SERVICE}-329557972822.${REGION}.run.app"

echo ""
echo "=================================================="
echo "  🛒 Bolta Bazaar — Production Redeploy"
echo "  Project : $PROJECT_ID"
echo "  Region  : $REGION"
echo "=================================================="
echo ""

# ---- Step 1: Set GCP project ----
echo "▶ Setting GCP project..."
gcloud config set project $PROJECT_ID

# ---- Step 2: Build & Deploy BACKEND ----
echo ""
echo "▶ Building backend Docker image..."
cd backend
gcloud builds submit \
  --tag $BACKEND_IMAGE \
  --timeout=10m \
  .

echo ""
echo "▶ Deploying backend to Cloud Run..."
gcloud run deploy $BACKEND_SERVICE \
  --image $BACKEND_IMAGE \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --set-secrets "GOOGLE_API_KEY=GOOGLE_API_KEY:latest" \
  --memory 512Mi \
  --timeout 120

echo "✅ Backend deployed: $BACKEND_URL"

# ---- Step 3: Build & Deploy FRONTEND ----
echo ""
echo "▶ Building frontend Docker image (with production API URL)..."
cd ../frontend
echo "VITE_API_URL=${BACKEND_URL}" > .env.production
gcloud builds submit \
  --tag $FRONTEND_IMAGE \
  --timeout=10m \
  .

echo ""
echo "▶ Deploying frontend to Cloud Run..."
gcloud run deploy $FRONTEND_SERVICE \
  --image $FRONTEND_IMAGE \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory 256Mi \
  --port 8080

FRONTEND_URL=$(gcloud run services describe $FRONTEND_SERVICE \
  --platform managed \
  --region $REGION \
  --format "value(status.url)")

echo ""
echo "=================================================="
echo "  ✅ ALL DONE!"
echo "  Frontend : $FRONTEND_URL"
echo "  Backend  : $BACKEND_URL"
echo "  API Test : ${BACKEND_URL}/api/inventory"
echo "=================================================="
