#!/bin/bash
#
# CrowdSurfer Captive Portal Deployment Script
# Builds and installs nodogsplash captive portal with portal server
#
# Usage: bash deploy_captive_portal.sh
#

set -e

echo "═══════════════════════════════════════════════════════════════"
echo "  CrowdSurfer Captive Portal Deployment"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Check if running as crowdsurfer user
if [ "$USER" != "crowdsurfer" ]; then
    echo "⚠️  Warning: This script should be run as the crowdsurfer user"
    echo "   Current user: $USER"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Step 1: Create database directory
echo "📁 Creating database directory..."
sudo mkdir -p /var/lib/crowdsurfer
sudo chown crowdsurfer:crowdsurfer /var/lib/crowdsurfer
echo "✅ Database directory created"
echo ""

# Step 2: Install build dependencies
echo "📦 Installing build dependencies..."
sudo apt-get update -qq
sudo apt-get install -y git build-essential libmicrohttpd-dev
echo "✅ Build dependencies installed"
echo ""

# Step 3: Build nodogsplash from source
echo "🔨 Building nodogsplash from source..."
cd /tmp
if [ -d "nodogsplash" ]; then
    rm -rf nodogsplash
fi
git clone --quiet https://github.com/nodogsplash/nodogsplash.git
cd nodogsplash
echo "   Compiling... (this takes 5-8 minutes)"
make -j$(nproc) > /dev/null 2>&1
sudo make install > /dev/null 2>&1
echo "✅ Nodogsplash built and installed"
echo ""

# Step 4: Download portal files from cs-pideploy
echo "📥 Downloading portal files from cs-pideploy..."
PORTAL_BASE="/opt/crowdsurfer/edge/portal"
mkdir -p "$PORTAL_BASE/static/css" "$PORTAL_BASE/static/js"

curl -sSL "https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/portal/portal_server.py" -o "$PORTAL_BASE/portal_server.py"
curl -sSL "https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/portal/validators.py" -o "$PORTAL_BASE/validators.py"
curl -sSL "https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/portal/nodogsplash_client.py" -o "$PORTAL_BASE/nodogsplash_client.py"
curl -sSL "https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/portal/models.py" -o "$PORTAL_BASE/models.py"
curl -sSL "https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/portal/static/splash.html" -o "$PORTAL_BASE/static/splash.html"
curl -sSL "https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/portal/static/survey.html" -o "$PORTAL_BASE/static/survey.html"
curl -sSL "https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/portal/static/css/portal.css" -o "$PORTAL_BASE/static/css/portal.css"
curl -sSL "https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/portal/static/js/portal.js" -o "$PORTAL_BASE/static/js/portal.js"
echo "✅ Portal files downloaded"
echo ""

# Step 5: Configure nodogsplash
echo "⚙️  Configuring nodogsplash..."
sudo mkdir -p /etc/nodogsplash
curl -sSL "https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/config/nodogsplash.conf" -o /tmp/nodogsplash.conf
sudo cp /tmp/nodogsplash.conf /etc/nodogsplash/nodogsplash.conf
echo "✅ Nodogsplash configured"
echo ""

# Step 6: Install systemd service files
echo "🔧 Installing systemd services..."
curl -sSL "https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/systemd/crowdsurfer-portal.service" -o /tmp/crowdsurfer-portal.service
sudo cp /tmp/crowdsurfer-portal.service /etc/systemd/system/crowdsurfer-portal.service
sudo systemctl daemon-reload
echo "✅ Systemd services installed"
echo ""

# Step 7: Start services
echo "🚀 Starting services..."
sudo systemctl enable crowdsurfer-portal
sudo systemctl start crowdsurfer-portal
sleep 2
sudo systemctl enable nodogsplash
sudo systemctl start nodogsplash
echo "✅ Services started"
echo ""

# Step 8: Verify deployment
echo "═══════════════════════════════════════════════════════════════"
echo "  Deployment Verification"
echo "═══════════════════════════════════════════════════════════════"
echo ""

echo "📊 Portal Server Status:"
sudo systemctl status crowdsurfer-portal --no-pager -l | head -n 10
echo ""

echo "📊 Nodogsplash Status:"
sudo systemctl status nodogsplash --no-pager -l | head -n 10
echo ""

echo "🧪 Testing Portal Health:"
if curl -s http://localhost:5000/portal/health > /dev/null 2>&1; then
    curl -s http://localhost:5000/portal/health | python3 -m json.tool
    echo ""
    echo "✅ Portal server is responding"
else
    echo "⚠️  Portal server is not responding yet (may need a moment to start)"
fi
echo ""

echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ Captive Portal Deployment Complete!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "🧪 Test from phone:"
echo "   1. Connect to CS-Shaka Wi-Fi"
echo "   2. Open browser (should auto-redirect to splash page)"
echo "   3. Fill out registration form"
echo "   4. Submit (should get internet access)"
echo ""
echo "🔧 Troubleshooting:"
echo "   View portal logs:      sudo journalctl -u crowdsurfer-portal -f"
echo "   View nodogsplash logs: sudo journalctl -u nodogsplash -f"
echo "   Restart services:      sudo systemctl restart crowdsurfer-portal nodogsplash"
echo "   Check nodogsplash:     sudo ndsctl status"
echo ""
