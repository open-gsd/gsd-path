#!/bin/bash
# Build GSDPathTray.app — compiles the Swift sources and wraps the binary in a
# minimal app bundle. Idempotent: safe to re-run.
set -euo pipefail

cd "$(dirname "$0")"

APP_DIR="build/GSDPathTray.app"
ARCH="$(uname -m)"

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

swiftc -O -whole-module-optimization \
    -target "${ARCH}-apple-macosx12.0" \
    -o "$APP_DIR/Contents/MacOS/GSDPathTray" \
    Sources/GSDPathTray/*.swift

cp AppIcon.icns "$APP_DIR/Contents/Resources/AppIcon.icns"

cat > "$APP_DIR/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>GSDPathTray</string>
    <key>CFBundleDisplayName</key>
    <string>OpenGSD Path</string>
    <key>CFBundleIdentifier</key>
    <string>org.gsd-path.tray</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>GSDPathTray</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
</dict>
</plist>
PLIST

if command -v codesign >/dev/null 2>&1; then
    codesign --force --sign - "$APP_DIR" >/dev/null
fi

echo "Built: $(cd "$(dirname "$APP_DIR")" && pwd)/$(basename "$APP_DIR")"
