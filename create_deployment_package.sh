#!/bin/bash
#
# CrowdSurfer Edge - Create Deployment Package
#
# This script creates a deployment package with all necessary edge files
# for deployment to a Raspberry Pi.
#
# Usage:
#   bash edge/create_deployment_package.sh
#
# Output:
#   crowdsurfer-edge-deployment.tar.gz
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_NAME="crowdsurfer-edge-deployment.tar.gz"

echo "Creating CrowdSurfer Edge deployment package..."
echo ""

# Create temporary directory
TEMP_DIR=$(mktemp -d)
PACKAGE_DIR="$TEMP_DIR/crowdsurfer-edge"
mkdir -p "$PACKAGE_DIR"

# Copy deployment script
echo "  ✓ Adding deployment script..."
cp "$SCRIPT_DIR/deploy_to_raspi_v4.sh" "$PACKAGE_DIR/"

# Copy edge service files
echo "  ✓ Adding edge service files..."
cp "$SCRIPT_DIR/telemetry_agent.py" "$PACKAGE_DIR/" 2>/dev/null || echo "    ⚠ telemetry_agent.py not found"
cp "$SCRIPT_DIR/management_agent.py" "$PACKAGE_DIR/" 2>/dev/null || echo "    ⚠ management_agent.py not found"
cp "$SCRIPT_DIR/portal_handler.py" "$PACKAGE_DIR/" 2>/dev/null || echo "    ⚠ portal_handler.py not found"
cp "$SCRIPT_DIR/queue.py" "$PACKAGE_DIR/" 2>/dev/null || echo "    ⚠ queue.py not found"
cp "$SCRIPT_DIR/config.py" "$PACKAGE_DIR/" 2>/dev/null || echo "    ⚠ config.py not found"

# Copy monitor
echo "  ✓ Adding heartbeat monitor..."
cp "$SCRIPT_DIR/monitor_heartbeat.py" "$PACKAGE_DIR/" 2>/dev/null || echo "    ⚠ monitor_heartbeat.py not found"

# Copy local admin server
echo "  ✓ Adding local admin server..."
cp "$SCRIPT_DIR/local_admin_server.py" "$PACKAGE_DIR/" 2>/dev/null || echo "    ⚠ local_admin_server.py not found"

# Copy requirements.txt if it exists
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "  ✓ Adding requirements.txt..."
    cp "$SCRIPT_DIR/requirements.txt" "$PACKAGE_DIR/"
fi

# Copy README
if [ -f "$SCRIPT_DIR/README.md" ]; then
    echo "  ✓ Adding README..."
    cp "$SCRIPT_DIR/README.md" "$PACKAGE_DIR/"
fi

# Create the tarball
echo ""
echo "Creating tarball..."
cd "$TEMP_DIR"
tar -czf "$PACKAGE_NAME" crowdsurfer-edge/

# Move to current directory
mv "$PACKAGE_NAME" "$SCRIPT_DIR/../$PACKAGE_NAME"

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo "✅ Deployment package created: $PACKAGE_NAME"
echo ""
echo "To deploy to Raspberry Pi:"
echo "  1. Copy package to Pi:"
echo "     scp $PACKAGE_NAME crowdsurfer@CS-Shaka:~/"
echo ""
echo "  2. On the Pi, extract and run:"
echo "     tar -xzf $PACKAGE_NAME"
echo "     cd crowdsurfer-edge"
echo "     sudo bash deploy_to_raspi_v4.sh"
echo ""
