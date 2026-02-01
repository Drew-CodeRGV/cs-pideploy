#!/bin/bash
#
# CrowdSurfer Bootstrap v1.0.0
# Public bootstrap for cs-pideploy repo
#
# Usage: curl -sSL https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/install.sh | sudo bash
#

set -e

# Script version
VERSION="1.0.1"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BACKEND_URL="${CROWDSURFER_BACKEND_URL:-https://crowdsurfer.politiquera.com}"
BOOTSTRAP_DIR="/opt/crowdsurfer-bootstrap"
CONFIG_DIR="/etc/crowdsurfer"
LOG_DIR="/var/log/crowdsurfer"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}CrowdSurfer Device Bootstrap${NC}"
echo -e "${GREEN}Version ${VERSION}${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Please run: sudo bash install.sh"
    exit 1
fi

# Check if running on Raspberry Pi
if [ ! -f /proc/cpuinfo ] || ! grep -q "Raspberry Pi" /proc/cpuinfo; then
    echo -e "${YELLOW}Warning: This does not appear to be a Raspberry Pi${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo -e "${BLUE}Backend URL: ${BACKEND_URL}${NC}"
echo ""

# Get device serial number
get_serial_number() {
    local SERIAL=$(cat /proc/cpuinfo | grep Serial | cut -d ' ' -f 2 | tail -c 5)
    echo "CS-SHAKA-V1-${SERIAL}"
}

DEVICE_SERIAL=$(get_serial_number)
echo -e "${BLUE}Device Serial: ${DEVICE_SERIAL}${NC}"
echo ""

echo -e "${GREEN}Step 1: Installing minimal dependencies...${NC}"
apt-get update
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    jq

echo -e "${GREEN}Step 2: Creating directories...${NC}"
mkdir -p "$BOOTSTRAP_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$LOG_DIR"

# Network Interface Configuration
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Step 3: Network Interface Configuration${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if network configuration already exists
SKIP_NETWORK_CONFIG=false
if [ -f "$CONFIG_DIR/network.conf" ]; then
    echo -e "${YELLOW}Existing network configuration found:${NC}"
    cat "$CONFIG_DIR/network.conf" | grep -E "^(WAN|LAN|MGMT)_INTERFACE" | sed 's/^/  /'
    echo ""
    echo -e "${YELLOW}Do you want to reconfigure network interfaces?${NC}"
    echo -e "${BLUE}Waiting 5 seconds... (press 'y' to reconfigure, any other key to skip)${NC}"
    echo ""
    
    read -t 5 -n 1 -p "Reconfigure? (y/N): " RECONFIG_CHOICE < /dev/tty || RECONFIG_CHOICE=""
    echo ""
    
    if [[ ! "$RECONFIG_CHOICE" =~ ^[Yy]$ ]]; then
        echo -e "${GREEN}✓ Using existing network configuration${NC}"
        SKIP_NETWORK_CONFIG=true
    else
        echo -e "${BLUE}Reconfiguring network interfaces...${NC}"
    fi
    echo ""
fi

if [ "$SKIP_NETWORK_CONFIG" = false ]; then
    # Detect available network interfaces (including down interfaces)
    echo -e "${BLUE}Detecting network interfaces...${NC}"
    INTERFACES=$(ip -o link show | awk -F': ' '{print $2}' | grep -v '^lo$' | grep -v '^docker' | grep -v '^veth')
    
    if [ -z "$INTERFACES" ]; then
        echo -e "${RED}Error: No network interfaces found${NC}"
        exit 1
    fi
    
    # Display available interfaces with details
    echo ""
    echo -e "${YELLOW}Available Network Interfaces (including down):${NC}"
    echo ""
    
    INTERFACE_ARRAY=()
    INDEX=1
    
    while IFS= read -r iface; do
        INTERFACE_ARRAY+=("$iface")
        
        # Get interface details
        IP_ADDR=$(ip -4 addr show "$iface" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' || echo "No IP")
        MAC_ADDR=$(ip link show "$iface" 2>/dev/null | grep -oP '(?<=link/ether\s)[0-9a-f:]+' || echo "N/A")
        STATE=$(ip link show "$iface" 2>/dev/null | grep -oP '(?<=state\s)\w+' || echo "UNKNOWN")
        
        # Determine interface type
        if [[ "$iface" == eth* ]]; then
            TYPE="Ethernet"
        elif [[ "$iface" == wlan* ]]; then
            TYPE="WiFi"
        elif [[ "$iface" == usb* ]]; then
            TYPE="USB"
        else
            TYPE="Other"
        fi
        
        # Color code based on state
        if [ "$STATE" = "UP" ]; then
            STATE_COLOR="${GREEN}"
        elif [ "$STATE" = "DOWN" ]; then
            STATE_COLOR="${RED}"
        else
            STATE_COLOR="${YELLOW}"
        fi
        
        echo -e "${GREEN}[$INDEX]${NC} ${BLUE}$iface${NC} ($TYPE) - ${STATE_COLOR}$STATE${NC}"
        echo "    MAC: $MAC_ADDR"
        echo "    IP:  $IP_ADDR"
        echo ""
        
        ((INDEX++))
    done <<< "$INTERFACES"
    
    # Prompt for WAN interface
    echo -e "${YELLOW}Select WAN (Internet) Interface:${NC}"
    echo -e "${BLUE}This interface connects to the internet (e.g., Starlink, Ethernet)${NC}"
    echo ""
    
    read -t 5 -p "Enter number [1-${#INTERFACE_ARRAY[@]}] (auto-select in 5 seconds): " WAN_CHOICE < /dev/tty || WAN_CHOICE=""
    
    if [ -z "$WAN_CHOICE" ]; then
        WAN_CHOICE=1
        echo ""
        echo -e "${YELLOW}⏱ Timeout - Auto-selected: ${INTERFACE_ARRAY[0]}${NC}"
    else
        echo ""
    fi
    
    # Validate WAN choice
    if ! [[ "$WAN_CHOICE" =~ ^[0-9]+$ ]] || [ "$WAN_CHOICE" -lt 1 ] || [ "$WAN_CHOICE" -gt "${#INTERFACE_ARRAY[@]}" ]; then
        echo -e "${RED}Invalid selection. Using default: ${INTERFACE_ARRAY[0]}${NC}"
        WAN_CHOICE=1
    fi
    
    WAN_INTERFACE="${INTERFACE_ARRAY[$((WAN_CHOICE-1))]}"
    echo -e "${GREEN}✓ WAN Interface: $WAN_INTERFACE${NC}"
    echo ""
    
    # Prompt for LAN interface
    echo -e "${YELLOW}Select LAN (Guest Access) Interface:${NC}"
    echo -e "${BLUE}This interface will host the WiFi access point for attendees${NC}"
    echo ""
    
    # Filter out WAN interface from options
    LAN_OPTIONS=()
    LAN_INDEX=1
    for iface in "${INTERFACE_ARRAY[@]}"; do
        if [ "$iface" != "$WAN_INTERFACE" ]; then
            LAN_OPTIONS+=("$iface")
            echo -e "${GREEN}[$LAN_INDEX]${NC} ${BLUE}$iface${NC}"
            ((LAN_INDEX++))
        fi
    done
    echo ""
    
    if [ ${#LAN_OPTIONS[@]} -eq 0 ]; then
        echo -e "${RED}Error: No available interfaces for LAN (all assigned to WAN)${NC}"
        exit 1
    fi
    
    read -t 5 -p "Enter number [1-${#LAN_OPTIONS[@]}] (auto-select in 5 seconds): " LAN_CHOICE < /dev/tty || LAN_CHOICE=""
    
    if [ -z "$LAN_CHOICE" ]; then
        LAN_CHOICE=1
        echo ""
        echo -e "${YELLOW}⏱ Timeout - Auto-selected: ${LAN_OPTIONS[0]}${NC}"
    else
        echo ""
    fi
    
    # Validate LAN choice
    if ! [[ "$LAN_CHOICE" =~ ^[0-9]+$ ]] || [ "$LAN_CHOICE" -lt 1 ] || [ "$LAN_CHOICE" -gt "${#LAN_OPTIONS[@]}" ]; then
        echo -e "${RED}Invalid selection. Using default: ${LAN_OPTIONS[0]}${NC}"
        LAN_CHOICE=1
    fi
    
    LAN_INTERFACE="${LAN_OPTIONS[$((LAN_CHOICE-1))]}"
    echo -e "${GREEN}✓ LAN Interface: $LAN_INTERFACE${NC}"
    echo ""
    
    # Prompt for Management interface (optional)
    echo -e "${YELLOW}Select Management Interface (optional):${NC}"
    echo -e "${BLUE}This interface is for SSH/admin access (can be same as WAN)${NC}"
    echo ""
    
    # Filter out WAN and LAN interfaces from options
    MGMT_OPTIONS=("$WAN_INTERFACE")  # WAN is always an option for management
    MGMT_INDEX=1
    echo -e "${GREEN}[$MGMT_INDEX]${NC} ${BLUE}$WAN_INTERFACE${NC} (same as WAN)"
    ((MGMT_INDEX++))
    
    for iface in "${INTERFACE_ARRAY[@]}"; do
        if [ "$iface" != "$WAN_INTERFACE" ] && [ "$iface" != "$LAN_INTERFACE" ]; then
            MGMT_OPTIONS+=("$iface")
            echo -e "${GREEN}[$MGMT_INDEX]${NC} ${BLUE}$iface${NC}"
            ((MGMT_INDEX++))
        fi
    done
    echo ""
    
    read -t 5 -p "Enter number [1-${#MGMT_OPTIONS[@]}] (auto-select WAN in 5 seconds): " MGMT_CHOICE < /dev/tty || MGMT_CHOICE=""
    
    if [ -z "$MGMT_CHOICE" ]; then
        MGMT_CHOICE=1
        echo ""
        echo -e "${YELLOW}⏱ Timeout - Auto-selected: ${MGMT_OPTIONS[0]} (same as WAN)${NC}"
    else
        echo ""
    fi
    
    # Validate Management choice
    if ! [[ "$MGMT_CHOICE" =~ ^[0-9]+$ ]] || [ "$MGMT_CHOICE" -lt 1 ] || [ "$MGMT_CHOICE" -gt "${#MGMT_OPTIONS[@]}" ]; then
        echo -e "${RED}Invalid selection. Using default: ${MGMT_OPTIONS[0]}${NC}"
        MGMT_CHOICE=1
    fi
    
    MGMT_INTERFACE="${MGMT_OPTIONS[$((MGMT_CHOICE-1))]}"
    echo -e "${GREEN}✓ Management Interface: $MGMT_INTERFACE${NC}"
    echo ""
    
    # Save network configuration
    echo -e "${BLUE}Saving network configuration...${NC}"
    cat > "$CONFIG_DIR/network.conf" <<NETCONF
# CrowdSurfer Network Configuration
# Generated: $(date)

WAN_INTERFACE=$WAN_INTERFACE
LAN_INTERFACE=$LAN_INTERFACE
MGMT_INTERFACE=$MGMT_INTERFACE
NETCONF
    
    chmod 644 "$CONFIG_DIR/network.conf"
    echo -e "${GREEN}✓ Network configuration saved to $CONFIG_DIR/network.conf${NC}"
    echo ""
else
    # Load existing configuration
    source "$CONFIG_DIR/network.conf"
    echo -e "${GREEN}✓ Loaded existing network configuration${NC}"
    echo ""
fi

echo -e "${GREEN}Step 4: Creating bootstrap agent...${NC}"

# Create minimal Python bootstrap agent
cat > "$BOOTSTRAP_DIR/bootstrap_agent.py" <<'PYTHON_SCRIPT'
#!/usr/bin/env python3
"""
CrowdSurfer Bootstrap Agent

Minimal agent that:
1. Registers device with backend
2. Polls for authorization
3. Downloads full edge system after authorization
"""

import requests
import json
import time
import sys
import os
import subprocess
import tarfile
import shutil
from pathlib import Path
from datetime import datetime

BACKEND_URL = os.getenv('CROWDSURFER_BACKEND_URL', 'https://crowdsurfer.politiquera.com')
CONFIG_DIR = Path('/etc/crowdsurfer')
BOOTSTRAP_DIR = Path('/opt/crowdsurfer-bootstrap')
INSTALL_DIR = Path('/opt/crowdsurfer')
LOG_FILE = Path('/var/log/crowdsurfer/bootstrap.log')

def log(message):
    """Log message to file and console."""
    timestamp = datetime.now().isoformat()
    log_message = f"{timestamp} - {message}"
    print(log_message)
    
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(log_message + '\n')

def get_serial_number():
    """Get device serial number."""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    cpu_serial = line.split(':')[1].strip()
                    suffix = cpu_serial[-3:]
                    return f"CS-SHAKA-V1-{suffix}"
    except Exception as e:
        log(f"Error reading serial: {e}")
    
    return "CS-SHAKA-V1-000"

def register_device(serial_number):
    """Register device with backend and get token."""
    log(f"Registering device: {serial_number}")
    
    try:
        url = f"{BACKEND_URL}/api/v1/devices/heartbeat"
        payload = {
            'serial_number': serial_number,
            'firmware_version': '0.0.1-bootstrap',
            'telemetry': {
                'cpu_usage': 0.0,
                'memory_usage': 0.0,
                'disk_usage': 0.0,
                'wifi_client_count': 0,
                'uptime_seconds': 0
            },
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        
        response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('device_token'):
                log(f"✓ Device registered successfully")
                return data['device_token']
            elif data.get('status') == 'unauthorized':
                log(f"⚠ Device not authorized yet: {data.get('message')}")
                return None
            else:
                log(f"⚠ Unexpected response: {data}")
                return None
        else:
            log(f"✗ Registration failed: {response.status_code}")
            return None
            
    except Exception as e:
        log(f"✗ Registration error: {e}")
        return None

def poll_for_authorization(serial_number):
    """Poll backend until device is authorized."""
    log("Waiting for admin authorization...")
    log("Admin must authorize this device in the CrowdSurfer admin panel")
    
    poll_interval = 10  # seconds
    max_attempts = 360  # 1 hour total
    
    for attempt in range(max_attempts):
        token = register_device(serial_number)
        
        if token:
            # Save token
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            config_file = CONFIG_DIR / 'device.conf'
            
            config_data = {
                'device_serial': serial_number,
                'device_token': token,
                'backend_url': BACKEND_URL
            }
            
            with open(config_file, 'w') as f:
                json.dump(config_data, f, indent=2)
            
            os.chmod(config_file, 0o644)
            
            log(f"✓ Device authorized! Token saved.")
            return token
        
        # Wait before next poll
        if attempt < max_attempts - 1:
            time.sleep(poll_interval)
    
    log("✗ Authorization timeout - device not authorized within 1 hour")
    return None

def download_deployment_package(token):
    """Download full edge system deployment package from backend."""
    log("Downloading deployment package from backend...")
    
    try:
        url = f"{BACKEND_URL}/api/v1/devices/deployment"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, headers=headers, timeout=60, stream=True)
        
        if response.status_code == 200:
            # Save deployment package
            package_file = BOOTSTRAP_DIR / 'deployment.tar.gz'
            
            with open(package_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            log(f"✓ Downloaded deployment package: {package_file}")
            return package_file
        else:
            log(f"✗ Failed to download deployment package: {response.status_code}")
            return None
            
    except Exception as e:
        log(f"✗ Download error: {e}")
        return None

def install_deployment_package(package_file):
    """Extract and install deployment package."""
    log("Installing deployment package...")
    
    try:
        # Create installation directory
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        
        # Extract package to /opt/crowdsurfer
        with tarfile.open(package_file, 'r:gz') as tar:
            tar.extractall(INSTALL_DIR)
        
        log(f"✓ Extracted deployment package to {INSTALL_DIR}")
        
        # Run installation script from package
        install_script = INSTALL_DIR / 'install.sh'
        
        if install_script.exists():
            log("Running installation script...")
            
            # Run installation script with extended timeout and real-time output
            process = subprocess.Popen(
                ['bash', str(install_script)],
                cwd=str(INSTALL_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # Stream output in real-time
            for line in process.stdout:
                log(line.rstrip())
            
            # Wait for completion
            return_code = process.wait()
            
            if return_code == 0:
                log("✓ Installation completed successfully")
                return True
            else:
                log(f"✗ Installation failed with exit code: {return_code}")
                return False
        else:
            log(f"✗ Installation script not found: {install_script}")
            return False
            
    except Exception as e:
        log(f"✗ Installation error: {e}")
        return False

def main():
    """Main bootstrap flow."""
    log("=" * 50)
    log("CrowdSurfer Bootstrap Agent Starting")
    log("=" * 50)
    
    # Get device serial
    serial_number = get_serial_number()
    log(f"Device Serial: {serial_number}")
    
    # Step 1: Register and wait for authorization
    token = poll_for_authorization(serial_number)
    
    if not token:
        log("✗ Bootstrap failed: Device not authorized")
        return 1
    
    # Step 2: Download deployment package
    package_file = download_deployment_package(token)
    
    if not package_file:
        log("✗ Bootstrap failed: Could not download deployment package")
        return 1
    
    # Step 3: Install deployment package
    if not install_deployment_package(package_file):
        log("✗ Bootstrap failed: Installation failed")
        return 1
    
    log("=" * 50)
    log("✓ Bootstrap completed successfully!")
    log("=" * 50)
    log("Full edge system is now installed and running")
    log("Access admin interface at: http://10.0.0.1:8080")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
PYTHON_SCRIPT

chmod +x "$BOOTSTRAP_DIR/bootstrap_agent.py"

echo -e "${GREEN}Step 5: Creating Python virtual environment...${NC}"
cd "$BOOTSTRAP_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install requests

echo -e "${GREEN}Step 6: Creating systemd service...${NC}"

cat > /etc/systemd/system/crowdsurfer-bootstrap.service <<EOF
[Unit]
Description=CrowdSurfer Bootstrap Agent
After=network.target

[Service]
Type=oneshot
Environment="CROWDSURFER_BACKEND_URL=$BACKEND_URL"
ExecStart=$BOOTSTRAP_DIR/venv/bin/python3 $BOOTSTRAP_DIR/bootstrap_agent.py
StandardOutput=append:$LOG_DIR/bootstrap.log
StandardError=append:$LOG_DIR/bootstrap.log
RemainAfterExit=yes
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable crowdsurfer-bootstrap

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Bootstrap Installation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}Device Information:${NC}"
echo "  Serial: $DEVICE_SERIAL"
echo "  Backend: $BACKEND_URL"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. This device will now register with the backend"
echo "2. An admin must authorize this device in the admin panel"
echo "3. After authorization, the full edge system will be downloaded and installed automatically"
echo ""
echo -e "${YELLOW}To monitor bootstrap progress:${NC}"
echo "  tail -f $LOG_DIR/bootstrap.log"
echo ""
echo -e "${YELLOW}Starting bootstrap agent...${NC}"

# Start bootstrap agent
systemctl start --no-block crowdsurfer-bootstrap

# Wait for service to start
sleep 5

# Check if service started successfully
if systemctl is-active --quiet crowdsurfer-bootstrap.service; then
    echo ""
    echo -e "${GREEN}✓ Bootstrap agent started successfully${NC}"
    echo ""
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}Device Registration in Progress${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    echo "The bootstrap agent is now running in the background."
    echo ""
    echo "Next steps:"
    echo "  1. The device is registering with the backend"
    echo "  2. Authorize device ${DEVICE_SERIAL} in the admin dashboard"
    echo "  3. Installation will complete automatically after authorization"
    echo ""
    echo "To monitor progress:"
    echo "  ${CYAN}tail -f $LOG_DIR/bootstrap.log${NC}"
    echo ""
    echo "To check status:"
    echo "  ${CYAN}systemctl status crowdsurfer-bootstrap${NC}"
    echo ""
else
    echo ""
    echo -e "${RED}✗ Bootstrap agent failed to start${NC}"
    echo ""
    echo "Check status with:"
    echo "  systemctl status crowdsurfer-bootstrap"
    echo ""
    echo "Check logs with:"
    echo "  tail -f $LOG_DIR/bootstrap.log"
    echo ""
    exit 1
fi
