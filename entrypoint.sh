#!/bin/bash

# Odota hetki ennen käynnistystä
sleep 5

# Tarkista ympäristömuuttujat
echo "=== Frigate SFTP Uploader ==="
echo "SFTP Host: ${SFTP_HOST}"
echo "SFTP Username: ${SFTP_USERNAME}"
echo "Frigate Directory: ${FRIGATE_CLIPS_DIR:-/media/frigate/clips}"
echo "Remote Directory: ${SFTP_REMOTE_DIR:-/uploads}"
echo "Upload Extensions: ${UPLOAD_EXTENSIONS:-[\"jpg\", \"jpeg\", \"png\", \"mp4\", \"avi\", \"mov\"]}"
echo "============================="

# Käynnistä Python-sovellus
exec python3 frigate_sftp_upload.py
