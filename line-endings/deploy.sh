#!/usr/bin/env bash
# Deploys the sample site.
set -euo pipefail

APP="sample-site"
TARGET="deploy@example.org"

echo "Deploying ${APP} to ${TARGET}"
scp -r ./dist/. "${TARGET}:/var/www/${APP}/"
ssh "${TARGET}" "sudo systemctl restart ${APP}.service"
echo "Done"
