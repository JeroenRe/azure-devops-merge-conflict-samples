#!/usr/bin/env bash
# Deploys the sample site.
set -euo pipefail

APP="sample-site"
TARGET="deploy@example.org"

echo "Deploying ${APP} to ${TARGET}"
rsync -az --delete --exclude "*.map" ./dist/ "${TARGET}:/var/www/${APP}/"
ssh "${TARGET}" "sudo systemctl reload ${APP}"
echo "Done"
