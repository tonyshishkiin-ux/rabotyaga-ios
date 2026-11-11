#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DERIVED_DATA="${RUNNER_TEMP:-/tmp}/RabotyagaDerivedData"
OUTPUT_DIR="$PROJECT_ROOT/build"
PACKAGE_DIR="$(mktemp -d "${RUNNER_TEMP:-/tmp}/rabotyaga-package.XXXXXX")"

mkdir -p "$OUTPUT_DIR" "$PACKAGE_DIR/Payload"

xcodebuild \
  -project "$PROJECT_ROOT/Rabotyaga.xcodeproj" \
  -scheme Rabotyaga \
  -configuration Release \
  -sdk iphoneos \
  -destination 'generic/platform=iOS' \
  -derivedDataPath "$DERIVED_DATA" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY='' \
  build

APP_PATH="$DERIVED_DATA/Build/Products/Release-iphoneos/Rabotyaga.app"
test -d "$APP_PATH"
ditto "$APP_PATH" "$PACKAGE_DIR/Payload/Rabotyaga.app"

(
  cd "$PACKAGE_DIR"
  zip -qry "$OUTPUT_DIR/Rabotyaga-unsigned.ipa" Payload
)

plutil -p "$APP_PATH/Info.plist"
file "$APP_PATH/Rabotyaga"
shasum -a 256 "$OUTPUT_DIR/Rabotyaga-unsigned.ipa"

