# ============================================================
# Bolta Bazaar - Redeploy Script (Windows PowerShell)
# ============================================================

$ErrorActionPreference = "Stop"

# ---- CONFIG ----
$PROJECT_ID = "bolta-bazaar"
$REGION = "asia-south1"
$BACKEND_SERVICE = "bolta-bazaar-backend"
$FRONTEND_SERVICE = "bolta-bazaar-frontend"
$BACKEND_IMAGE = "gcr.io/$PROJECT_ID/$BACKEND_SERVICE"
$FRONTEND_IMAGE = "gcr.io/$PROJECT_ID/$FRONTEND_SERVICE"

Write-Host ""
Write-Host "=================================================="
Write-Host "  Bolta Bazaar - Dynamic Production Redeploy"
Write-Host "=================================================="
Write-Host ""

# ---- Step 1: Set GCP project ----
Write-Host "Step 1: Setting GCP project..."
gcloud config set project $PROJECT_ID

# ---- Step 2: Build & Deploy BACKEND ----
Write-Host ""
Write-Host "Step 2: Building backend image..."
Set-Location backend
gcloud builds submit --tag $BACKEND_IMAGE --timeout=10m .

Write-Host ""
Write-Host "Step 3: Deploying backend..."
gcloud run deploy $BACKEND_SERVICE `
  --image $BACKEND_IMAGE `
  --platform managed `
  --region $REGION `
  --allow-unauthenticated `
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID" `
  --set-secrets "GOOGLE_API_KEY=GOOGLE_API_KEY:latest" `
  --memory 512Mi `
  --timeout 120

# DYNAMICALLY GET THE REAL BACKEND URL
$BACKEND_URL = gcloud run services describe $BACKEND_SERVICE --platform managed --region $REGION --format "value(status.url)"
Write-Host "Backend is live at: $BACKEND_URL" -ForegroundColor Green

# ---- Step 3: Build & Deploy FRONTEND ----
Write-Host ""
Write-Host "Step 4: Building frontend with real API URL..."
Set-Location ../frontend

# Use Set-Content with UTF8 (No BOM) logic via .NET to be safe
$EnvContent = "VITE_API_URL=$BACKEND_URL"
[System.IO.File]::WriteAllLines((Join-Path (Get-Location) ".env.production"), $EnvContent)

gcloud builds submit --tag $FRONTEND_IMAGE --timeout=10m .

Write-Host ""
Write-Host "Step 5: Deploying frontend..."
gcloud run deploy $FRONTEND_SERVICE `
  --image $FRONTEND_IMAGE `
  --platform managed `
  --region $REGION `
  --allow-unauthenticated `
  --memory 256Mi `
  --port 8080

$FRONTEND_URL = gcloud run services describe $FRONTEND_SERVICE --platform managed --region $REGION --format "value(status.url)"

Set-Location ..

Write-Host ""
Write-Host "=================================================="
Write-Host "  DEPLOYMENT COMPLETE & SYNCED!"
Write-Host "  Frontend : $FRONTEND_URL"
Write-Host "  Backend  : $BACKEND_URL"
Write-Host "=================================================="
Write-Host ""
