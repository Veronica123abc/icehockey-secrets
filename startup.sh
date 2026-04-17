#!/bin/bash
# Azure Web App startup command
# Set as the startup command in Azure Portal > Configuration > General settings
gunicorn --bind=0.0.0.0:8000 --timeout 120 --workers 2 app:app
