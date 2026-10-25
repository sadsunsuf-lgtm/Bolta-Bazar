import os

def get_content(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

files = {
    "bolta-bazaar/backend/requirements.txt": "backend/requirements.txt",
    "bolta-bazaar/backend/main.py": "backend/main.py",
    "bolta-bazaar/backend/Dockerfile": "backend/Dockerfile",
    "bolta-bazaar/backend/services/voice_processor.py": "backend/services/voice_processor.py",
    "bolta-bazaar/backend/services/firestore_service.py": "backend/services/firestore_service.py",
    "bolta-bazaar/frontend/package.json": "frontend/package.json",
    "bolta-bazaar/frontend/vite.config.js": "frontend/vite.config.js",
    "bolta-bazaar/frontend/index.html": "frontend/index.html",
    "bolta-bazaar/frontend/Dockerfile": "frontend/Dockerfile",
    "bolta-bazaar/frontend/nginx.conf": "frontend/nginx.conf",
    "bolta-bazaar/frontend/src/App.jsx": "frontend/src/App.jsx",
    "bolta-bazaar/frontend/src/components/VoiceRecorder.jsx": "frontend/src/components/VoiceRecorder.jsx",
}

bash_script = """#!/bin/bash
set -e

# Create directories
mkdir -p bolta-bazaar/backend/services
mkdir -p bolta-bazaar/frontend/src/components

"""

for target, source in files.items():
    content = get_content(source)
    # Use heredoc with quoted EOF to prevent variable expansion
    bash_script += f'cat <<\'EOF\' > {target}\n{content}\nEOF\n\n'

bash_script += """
echo "Files created successfully."

# Enable APIs
gcloud services enable artifactregistry.googleapis.com cloudbuild.googleapis.com run.googleapis.com

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
"""

with open('setup_cloud_shell_final.sh', 'w', encoding='utf-8') as f:
    f.write(bash_script)

print("setup_cloud_shell_final.sh generated.")
