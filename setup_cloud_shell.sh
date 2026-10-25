#!/bin/bash
set -e

# Create directories
mkdir -p bolta-bazaar/backend/services
mkdir -p bolta-bazaar/frontend/src/components

# Function to create file
create_file() {
    cat <<EOF > "$1"
$2
EOF
}

# Backend Files
create_file "bolta-bazaar/backend/requirements.txt" "$(cat backend/requirements.txt)"
create_file "bolta-bazaar/backend/main.py" "$(cat backend/main.py)"
create_file "bolta-bazaar/backend/Dockerfile" "$(cat backend/Dockerfile)"
create_file "bolta-bazaar/backend/services/voice_processor.py" "$(cat backend/services/voice_processor.py)"
create_file "bolta-bazaar/backend/services/firestore_service.py" "$(cat backend/services/firestore_service.py)"

# Frontend Files
create_file "bolta-bazaar/frontend/package.json" "$(cat frontend/package.json)"
create_file "bolta-bazaar/frontend/vite.config.js" "$(cat frontend/vite.config.js)"
create_file "bolta-bazaar/frontend/index.html" "$(cat frontend/index.html)"
create_file "bolta-bazaar/frontend/Dockerfile" "$(cat frontend/Dockerfile)"
create_file "bolta-bazaar/frontend/nginx.conf" "$(cat frontend/nginx.conf)"
create_file "bolta-bazaar/frontend/src/App.jsx" "$(cat frontend/src/App.jsx)"
create_file "bolta-bazaar/frontend/src/components/VoiceRecorder.jsx" "$(cat frontend/src/components/VoiceRecorder.jsx)"

echo "Files created successfully in bolta-bazaar directory."

# Deploy Backend
cd bolta-bazaar/backend
gcloud builds submit --tag gcr.io/bolta-bazaar/backend .
gcloud run deploy bolta-bazaar-backend --image gcr.io/bolta-bazaar/backend --region asia-south1 --set-secrets="GOOGLE_API_KEY=GOOGLE_API_KEY:latest" --allow-unauthenticated

# Get Backend URL
BACKEND_URL=$(gcloud run services describe bolta-bazaar-backend --region asia-south1 --format 'value(status.url)')

# Build and Deploy Frontend
cd ../frontend
gcloud builds submit --tag gcr.io/bolta-bazaar/frontend --build-arg VITE_API_URL=$BACKEND_URL .
gcloud run deploy bolta-bazaar-frontend --image gcr.io/bolta-bazaar/frontend --region asia-south1 --allow-unauthenticated

echo "Deployment complete!"
