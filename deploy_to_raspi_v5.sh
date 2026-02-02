#!/bin/bash
#
# CrowdSurfer Shaka Edge Device - Raspberry Pi Deployment Script v5
#
# Version: 5.0.0
# Last Updated: 2026-01-28
#
# This script deploys the complete CrowdSurfer edge device software to a Raspberry Pi
# with interactive network interface configuration.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Drew-CodeRGV/CrowdSurfer/master/edge/deploy_to_raspi_v5.sh | sudo bash
#
# Or manually:
#   sudo bash deploy_to_raspi_v5.sh
#

set -e  # Exit on error

SCRIPT_VERSION="5.0.2"
CS_PIDEPLOY_URL="https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/Drew-CodeRGV/CrowdSurfer.git"
INSTALL_DIR="/opt/crowdsurfer"
CONFIG_DIR="/etc/crowdsurfer"
CACHE_DIR="/var/cache/crowdsurfer"
LOG_DIR="/var/log/crowdsurfer"
BACKEND_URL="${CROWDSURFER_BACKEND_URL:-https://crowdsurfer.politiquera.com}"

# Network interface configuration (will be set interactively)
WAN_INTERFACE=""
MANAGEMENT_INTERFACE=""
CLIENT_INTERFACES=()

# Function to list interfaces with assignment status
list_interfaces_with_status() {
    echo ""
    echo "=========================================="
    echo "Available Network Interfaces"
    echo "=========================================="
    
    local idx=1
    for iface in $(ls /sys/class/net/ | grep -v lo); do
        local status="DOWN"
        local ip=""
        local assignment=""
        
        if ip link show "$iface" | grep -q "state UP"; then
            status="UP"
            ip=$(ip addr show "$iface" | grep "inet " | awk '{print $2}' | head -n1)
        fi
        
        # Check if already assigned
        if [ "$iface" = "$WAN_INTERFACE" ]; then
            assignment=" [ASSIGNED: WAN]"
        elif [ "$iface" = "$MANAGEMENT_INTERFACE" ]; then
            assignment=" [ASSIGNED: Management]"
        fi
        
        echo -e "${idx}. ${CYAN}${iface}${NC} - Status: ${status} ${ip:+IP: $ip}${assignment}"
        idx=$((idx + 1))
    done
    echo "=========================================="
    echo ""
}

# Print functions
print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

# Function to download file from cs-pideploy
download_file() {
    local filename="$1"
    local dest_path="$2"
    local url="${CS_PIDEPLOY_URL}/${filename}"
    
    print_info "Downloading $filename from cs-pideploy..."
    if curl -sSL "$url" -o "$dest_path" 2>/dev/null; then
        print_success "Downloaded $filename"
        return 0
    else
        print_warning "Failed to download $filename (will use existing if available)"
        return 1
    fi
}

# Function to detect and install USB WiFi adapter drivers
detect_and_install_wifi_drivers() {
    print_header "Detecting USB WiFi Adapters"
    
    # Check for USB WiFi adapters that need drivers
    local needs_driver=false
    local driver_type=""
    
    # Detect Edimax AC600 (RTL8812AU chipset)
    if lsusb | grep -q "7392:a812"; then
        print_warning "Detected: Edimax AC600 USB WiFi adapter"
        print_info "This adapter requires RTL8812AU driver installation"
        needs_driver=true
        driver_type="8812au"
    fi
    
    # Detect other RTL8812AU devices
    if lsusb | grep -qE "0bda:8812|0bda:881a|0bda:881b|0bda:881c"; then
        print_warning "Detected: Realtek RTL8812AU USB WiFi adapter"
        print_info "This adapter requires RTL8812AU driver installation"
        needs_driver=true
        driver_type="8812au"
    fi
    
    # Detect RTL8814AU devices
    if lsusb | grep -qE "0bda:8813"; then
        print_warning "Detected: Realtek RTL8814AU USB WiFi adapter"
        print_info "This adapter requires RTL8814AU driver installation"
        needs_driver=true
        driver_type="8814au"
    fi
    
    if [ "$needs_driver" = false ]; then
        print_success "No USB WiFi adapters requiring driver installation detected"
        return 0
    fi
    
    # Ask user if they want to install the driver
    echo ""
    print_warning "USB WiFi adapter detected that requires driver installation"
    echo "Without the driver, this adapter will not create a network interface (wlan1)."
    echo ""
    read -p "Install driver now? This will take 5-10 minutes. (Y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]] && [[ ! -z $REPLY ]]; then
        print_warning "Skipping driver installation. USB WiFi adapter will not be available."
        return 0
    fi
    
    print_header "Installing USB WiFi Driver: $driver_type"
    
    # Install build dependencies (suppress error about kernel headers)
    print_info "Installing build dependencies..."
    apt-get install -y git dkms build-essential bc 2>&1 | grep -v "^Reading\|^Building\|^Unpacking\|^Setting" > /dev/null || true
    apt-get install -y raspberrypi-kernel-headers 2>&1 | grep -v "^Reading\|^Building\|^Unpacking\|Unable to locate" > /dev/null || true
    
    if [ "$driver_type" = "8812au" ]; then
        # Install RTL8812AU driver
        print_info "Downloading RTL8812AU driver..."
        cd /tmp
        if [ -d "8812au-20210820" ]; then
            rm -rf 8812au-20210820
        fi
        git clone --depth 1 --quiet https://github.com/morrownr/8812au-20210820.git 2>/dev/null
        
        print_info "Compiling and installing driver (this takes 3-5 minutes)..."
        cd 8812au-20210820
        
        # Run install in background and show progress
        ./install-driver.sh > /tmp/driver_install.log 2>&1 &
        local install_pid=$!
        
        # Show percentage progress (estimated based on typical 240 second compile time)
        local elapsed=0
        local max_time=240  # 4 minutes estimated
        printf "  Progress: %3d%%" 0
        
        while kill -0 $install_pid 2>/dev/null; do
            sleep 2
            elapsed=$((elapsed + 2))
            local percent=$((elapsed * 100 / max_time))
            if [ $percent -gt 99 ]; then
                percent=99
            fi
            printf "\r  Progress: %3d%%" $percent
        done
        printf "\r  Progress: 100%%\n"
        
        # Check if installation succeeded
        wait $install_pid
        local exit_code=$?
        
        if [ $exit_code -eq 0 ]; then
            print_success "RTL8812AU driver installed successfully"
        else
            print_warning "Driver installation completed with warnings (this is usually OK)"
        fi
    elif [ "$driver_type" = "8814au" ]; then
        # Install RTL8814AU driver
        print_info "Downloading RTL8814AU driver..."
        cd /tmp
        if [ -d "8814au" ]; then
            rm -rf 8814au
        fi
        git clone --depth 1 --quiet https://github.com/morrownr/8814au.git 2>/dev/null
        
        print_info "Compiling and installing driver (this takes 3-5 minutes)..."
        cd 8814au
        
        # Run install in background and show progress
        ./install-driver.sh > /tmp/driver_install.log 2>&1 &
        local install_pid=$!
        
        # Show percentage progress (estimated based on typical 240 second compile time)
        local elapsed=0
        local max_time=240  # 4 minutes estimated
        printf "  Progress: %3d%%" 0
        
        while kill -0 $install_pid 2>/dev/null; do
            sleep 2
            elapsed=$((elapsed + 2))
            local percent=$((elapsed * 100 / max_time))
            if [ $percent -gt 99 ]; then
                percent=99
            fi
            printf "\r  Progress: %3d%%" $percent
        done
        printf "\r  Progress: 100%%\n"
        
        # Check if installation succeeded
        wait $install_pid
        local exit_code=$?
        
        if [ $exit_code -eq 0 ]; then
            print_success "RTL8814AU driver installed successfully"
        else
            print_warning "Driver installation completed with warnings (this is usually OK)"
        fi
    fi
    
    # Load the driver
    print_info "Loading driver module..."
    modprobe $driver_type 2>/dev/null || true
    sleep 2
    
    # Verify interface was created
    local new_interfaces=$(ls /sys/class/net/ | grep -E "wlan[1-9]" || true)
    if [ -n "$new_interfaces" ]; then
        print_success "New wireless interface(s) detected: $new_interfaces"
    else
        print_warning "Driver installed but interface not yet visible. May appear after reboot."
    fi
    
    echo ""
}

# Function to list available network interfaces (simplified without colors)
list_interfaces() {
    echo ""
    echo "Available network interfaces:"
    echo "----------------------------"
    
    local idx=1
    for iface in $(ls /sys/class/net/ | grep -v lo); do
        local status="DOWN"
        local ip=""
        
        if ip link show "$iface" | grep -q "state UP"; then
            status="UP"
            ip=$(ip addr show "$iface" | grep "inet " | awk '{print $2}' | head -n1)
        fi
        
        echo "${idx}. ${iface} - Status: ${status} ${ip:+IP: $ip}"
        idx=$((idx + 1))
    done
    echo ""
    echo "Note: DOWN interfaces (like USB WiFi adapters) can be selected"
    echo "      They will be automatically brought UP when you select them"
    echo ""
}

# Function to select interface with improved UX
select_interface() {
    local prompt="$1"
    local default="$2"
    local selected=""
    
    while true; do
        echo ""
        echo ""
        list_interfaces_with_status
        
        echo -e "${YELLOW}${prompt}${NC}"
        if [ -n "$default" ]; then
            echo "Press Enter for default: ${default}"
        fi
        echo ""
        read -p "Enter interface name (e.g., eth0) or number (e.g., 1): " selected
        
        # Use default if empty
        if [ -z "$selected" ] && [ -n "$default" ]; then
            selected="$default"
        fi
        
        # Check if input is a number
        if [[ "$selected" =~ ^[0-9]+$ ]]; then
            # Convert number to interface name
            local idx=1
            for iface in $(ls /sys/class/net/ | grep -v lo); do
                if [ "$idx" -eq "$selected" ]; then
                    selected="$iface"
                    break
                fi
                idx=$((idx + 1))
            done
        fi
        
        # Check if interface exists (even if DOWN)
        if [ -e "/sys/class/net/$selected" ]; then
            # Try to bring interface UP if it's DOWN
            if ! ip link show "$selected" | grep -q "state UP"; then
                print_info "Interface $selected is DOWN. Bringing it UP..."
                ip link set "$selected" up 2>/dev/null || true
                sleep 1
            fi
            echo ""
            print_success "Selected: $selected"
            echo ""
            echo "$selected"
            return 0
        else
            # Allow hardcoding interfaces that don't exist yet (e.g., wlan1 before driver install)
            print_warning "Interface '$selected' not found, but will be configured anyway."
            print_info "Make sure to install required drivers after deployment."
            echo ""
            print_success "Selected: $selected (will be configured when available)"
            echo ""
            echo "$selected"
            return 0
        fi
    done
}

# Function to select client interface with improved UX
select_client_interface() {
    local prompt="$1"
    local selected=""
    
    echo ""
    echo ""
    list_interfaces_with_status
    
    echo -e "${YELLOW}${prompt}${NC}"
    echo ""
    echo "Note: You can type 'wlan1' even if it doesn't exist yet!"
    echo "      (Install the USB WiFi driver after deployment)"
    echo ""
    read -p "Enter interface name (e.g., wlan1) or number, or type 'none' to skip: " selected
    
    if [ "$selected" = "none" ] || [ -z "$selected" ]; then
        echo ""
        print_info "No client interface selected (management only mode)"
        echo ""
        return 0
    fi
    
    # Check if input is a number
    if [[ "$selected" =~ ^[0-9]+$ ]]; then
        # Convert number to interface name
        local idx=1
        for iface in $(ls /sys/class/net/ | grep -v lo); do
            if [ "$idx" -eq "$selected" ]; then
                selected="$iface"
                break
            fi
            idx=$((idx + 1))
        done
    fi
    
    # Check if interface exists (even if DOWN)
    if [ -e "/sys/class/net/$selected" ]; then
        # Try to bring interface UP if it's DOWN
        if ! ip link show "$selected" | grep -q "state UP"; then
            print_info "Interface $selected is DOWN. Bringing it UP..."
            ip link set "$selected" up 2>/dev/null || true
            sleep 1
        fi
        echo ""
        print_success "Selected: $selected"
        echo ""
    else
        # Allow hardcoding interfaces that don't exist yet (e.g., wlan1 before driver install)
        print_warning "Interface '$selected' not found, but will be configured anyway."
        print_info "Make sure to install required drivers after deployment."
        echo ""
        print_success "Selected: $selected (will be configured when available)"
        echo ""
    fi
    
    echo "$selected"
    return 0
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    print_error "This script must be run as root (use sudo)"
    exit 1
fi

# Check if running on Raspberry Pi
if [ ! -f /proc/cpuinfo ] || ! grep -q "Raspberry Pi" /proc/cpuinfo; then
    print_warning "This doesn't appear to be a Raspberry Pi"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

print_header "CrowdSurfer Shaka Edge Device Deployment v${SCRIPT_VERSION}"
echo "This script will install and configure the CrowdSurfer edge device software"
echo "with interactive network interface configuration."
echo ""
echo "Installation directory: $INSTALL_DIR"
echo "Backend URL: $BACKEND_URL"
echo ""
print_info "Note: USB WiFi driver installation has been moved to post-deployment"
print_info "You can select wlan1 now and install the driver manually after setup"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# ============================================================================
# Network Interface Configuration
# ============================================================================
# Note: USB WiFi driver installation removed due to SSH stability issues
# Install drivers manually after deployment if needed

print_header "Network Interface Configuration"
echo ""
echo "Default Configuration:"
echo -e "  ${CYAN}WAN Interface:${NC}        eth0  (Internet connection)"
echo -e "  ${CYAN}Management Interface:${NC} wlan0 (Admin WiFi at 10.0.0.1)"
echo -e "  ${CYAN}Client Interface:${NC}     wlan1 (Event WiFi with DHCP)"
echo ""
echo "This will configure:"
echo "  • eth0 → Routes all traffic to internet"
echo "  • wlan0 → Management WiFi (SSID: CrowdSurfer-Admin)"
echo "  • wlan1 → Client WiFi with DHCP (SSID: CrowdSurfer-WiFi)"
echo ""

# 5-second timeout to customize
echo -n "Press 'c' within 5 seconds to customize, or wait to use defaults..."
if read -t 5 -n 1 -r customize && [[ $customize =~ ^[Cc]$ ]]; then
    echo ""
    echo ""
    print_info "Entering custom configuration mode..."
    
    # Show available interfaces
    echo ""
    echo "=========================================="
    echo "Available Network Interfaces on This Device"
    echo "=========================================="
    idx=1
    for iface in $(ls /sys/class/net/ | grep -v lo); do
        status="DOWN"
        ip=""
        
        if ip link show "$iface" | grep -q "state UP"; then
            status="UP"
            ip=$(ip addr show "$iface" | grep "inet " | awk '{print $2}' | head -n1)
        fi
        
        echo -e "${idx}. ${CYAN}${iface}${NC} - Status: ${status} ${ip:+IP: $ip}"
        idx=$((idx + 1))
    done
    echo "=========================================="
    echo ""
    
    # Select WAN interface
    print_info "Step 1: Select WAN Interface (Internet Connection)"
    WAN_INTERFACE=$(select_interface "Which interface connects to the internet?" "eth0")
    echo ""
    
    # Select Management interface
    print_info "Step 2: Select Management Interface (Local Admin WiFi)"
    MANAGEMENT_INTERFACE=$(select_interface "Which interface should serve the management WiFi?" "wlan0")
    echo ""
    
    # Select Client interface
    print_info "Step 3: Select Client Interface (Serve WiFi to Attendees)"
    echo ""
    echo "This interface will serve WiFi to event attendees."
    echo "Common choice: wlan1 (USB WiFi adapter)"
    echo ""
    CLIENT_INTERFACE=$(select_client_interface "Which interface should serve clients?")
    if [ -n "$CLIENT_INTERFACE" ]; then
        CLIENT_INTERFACES=("$CLIENT_INTERFACE")
    else
        CLIENT_INTERFACES=()
    fi
else
    echo ""
    echo ""
    print_success "Using default configuration"
    
    # Set defaults
    WAN_INTERFACE="eth0"
    MANAGEMENT_INTERFACE="wlan0"
    CLIENT_INTERFACE="wlan1"
    CLIENT_INTERFACES=("wlan1")
fi

echo ""

# Confirm configuration
print_header "Network Configuration Summary"
echo ""
echo -e "WAN Interface (Internet):     ${CYAN}$WAN_INTERFACE${NC}"
echo -e "Management Interface (Admin): ${CYAN}$MANAGEMENT_INTERFACE${NC}"
if [ ${#CLIENT_INTERFACES[@]} -gt 0 ]; then
    echo -e "Client Interfaces (Attendees): ${CYAN}${CLIENT_INTERFACES[@]}${NC}"
else
    echo -e "Client Interfaces (Attendees): ${YELLOW}None (management only)${NC}"
fi
echo ""
read -p "Is this configuration correct? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Configuration cancelled. Please run the script again."
    exit 1
fi

# ============================================================================
# System Setup
# ============================================================================

# Step 1: Update system
print_header "Step 1: Updating System"
apt-get update
apt-get upgrade -y
print_success "System updated"

# Step 2: Install dependencies
print_header "Step 2: Installing Dependencies"
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    hostapd \
    dnsmasq \
    iptables \
    sqlite3 \
    nginx \
    jq \
    dos2unix

# Note: nodogsplash is optional and not available in all repos
# We'll handle captive portal functionality in the Python code instead
print_success "Dependencies installed"

# Step 3: Setup Installation Directory
print_header "Step 3: Setting Up Installation Directory"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -d "$INSTALL_DIR" ]; then
    print_success "Installation directory already exists: $INSTALL_DIR"
    print_info "Checking for edge files to copy..."
else
    print_info "Creating installation directory..."
    mkdir -p "$INSTALL_DIR/edge"
fi

# Copy edge files from script directory if they exist, or download from cs-pideploy
EDGE_FILES=(
    "management_agent.py"
    "config.py"
    "telemetry_agent.py"
    "telemetry_queue.py"
    "requirements.txt"
)

EDGE_FILES_COPIED=0
for file in "${EDGE_FILES[@]}"; do
    if [ -f "$SCRIPT_DIR/$file" ]; then
        print_info "Copying $file from package..."
        cp "$SCRIPT_DIR/$file" "$INSTALL_DIR/edge/"
        EDGE_FILES_COPIED=$((EDGE_FILES_COPIED + 1))
    else
        print_info "$file not in package, downloading from cs-pideploy..."
        download_file "$file" "$INSTALL_DIR/edge/$file" || {
            if [ ! -f "$INSTALL_DIR/edge/$file" ]; then
                print_error "Failed to get $file and no existing file found"
                exit 1
            fi
        }
        EDGE_FILES_COPIED=$((EDGE_FILES_COPIED + 1))
    fi
done

if [ $EDGE_FILES_COPIED -gt 0 ]; then
    print_success "Installed $EDGE_FILES_COPIED edge file(s) with SSID inheritance support"
else
    print_error "No edge files found or downloaded"
    exit 1
fi

# Step 4: Create Python virtual environment
print_header "Step 4: Setting Up Python Environment"
if [ ! -d "$INSTALL_DIR/edge" ]; then
    print_warning "Edge directory doesn't exist, creating it..."
    mkdir -p "$INSTALL_DIR/edge"
fi

# Check if requirements.txt exists
if [ ! -f "$INSTALL_DIR/edge/requirements.txt" ]; then
    print_warning "requirements.txt not found in $INSTALL_DIR/edge"
    print_info "Creating minimal requirements.txt for basic functionality..."
    cat > "$INSTALL_DIR/edge/requirements.txt" << 'EOFREQ'
# CrowdSurfer Edge Device Requirements
requests==2.31.0
Flask==3.0.0
python-json-logger==2.0.7
EOFREQ
    print_success "Minimal requirements.txt created"
fi

cd "$INSTALL_DIR/edge"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_success "Virtual environment created"
fi

source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
print_success "Python dependencies installed"

# Step 5: Create directories
print_header "Step 5: Creating Directories"
mkdir -p "$CONFIG_DIR"
mkdir -p "$CACHE_DIR"
mkdir -p "$LOG_DIR"
chmod 700 "$CONFIG_DIR"
chmod 755 "$CACHE_DIR"
chmod 755 "$LOG_DIR"
print_success "Directories created"

# Step 6: Save network configuration
print_header "Step 6: Saving Network Configuration"
cat > "$CONFIG_DIR/network.conf" << EOF
{
  "wan_interface": "$WAN_INTERFACE",
  "management_interface": "$MANAGEMENT_INTERFACE",
  "client_interfaces": [$(printf '"%s",' "${CLIENT_INTERFACES[@]}" | sed 's/,$//')]
}
EOF
chmod 600 "$CONFIG_DIR/network.conf"
print_success "Network configuration saved"

# Step 7: Configure environment
print_header "Step 7: Configuring Environment"
cat > /etc/environment << EOF
CROWDSURFER_BACKEND_URL=$BACKEND_URL
CROWDSURFER_WAN_INTERFACE=$WAN_INTERFACE
CROWDSURFER_MANAGEMENT_INTERFACE=$MANAGEMENT_INTERFACE
EOF
print_success "Environment configured"

# Step 8: Configure WiFi Access Point (Management Interface)
print_header "Step 8: Configuring Management WiFi AP"

# Ensure network interfaces directory exists
mkdir -p /etc/network/interfaces.d

# Configure hostapd for management interface
cat > /etc/hostapd/hostapd.conf << EOF
interface=$MANAGEMENT_INTERFACE
driver=nl80211
ssid=CrowdSurfer-Admin
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=crowdsurfer2024
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# Configure dnsmasq for management interface
cat > /etc/dnsmasq.conf << EOF
# Management Interface (Admin WiFi)
interface=$MANAGEMENT_INTERFACE
dhcp-range=10.0.0.10,10.0.0.250,255.255.255.0,24h
dhcp-option=3,10.0.0.1
dhcp-option=6,10.0.0.1
listen-address=10.0.0.1
EOF

# Add client interface DHCP configuration if wlan1 is configured
if [ ${#CLIENT_INTERFACES[@]} -gt 0 ]; then
    for iface in "${CLIENT_INTERFACES[@]}"; do
        cat >> /etc/dnsmasq.conf << EOF

# Client Interface (Event Attendee WiFi)
interface=$iface
dhcp-range=192.168.100.10,192.168.100.250,255.255.255.0,24h
dhcp-option=3,192.168.100.1
dhcp-option=6,192.168.100.1
listen-address=192.168.100.1
EOF
    done
fi

cat >> /etc/dnsmasq.conf << EOF

# DNS servers
server=8.8.8.8
server=8.8.4.4
log-queries
log-dhcp
EOF

# Configure network interface for management
cat > "/etc/network/interfaces.d/${MANAGEMENT_INTERFACE}" << EOF
auto $MANAGEMENT_INTERFACE
iface $MANAGEMENT_INTERFACE inet static
    address 10.0.0.1
    netmask 255.255.255.0
EOF

print_success "Management WiFi AP configured on $MANAGEMENT_INTERFACE"

# Step 9: Configure Client Interfaces (if any)
if [ ${#CLIENT_INTERFACES[@]} -gt 0 ]; then
    print_header "Step 9: Configuring Client Interfaces"
    
    for iface in "${CLIENT_INTERFACES[@]}"; do
        print_info "Configuring $iface for client serving..."
        
        # Configure hostapd for client interface
        cat > "/etc/hostapd/hostapd-${iface}.conf" << EOF
interface=$iface
driver=nl80211
ssid=CrowdSurfer-WiFi
hw_mode=g
channel=11
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=crowdsurfer2024
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF
        
        # Configure network interface for client WiFi
        cat > "/etc/network/interfaces.d/${iface}" << EOF
auto $iface
iface $iface inet static
    address 192.168.100.1
    netmask 255.255.255.0
EOF
        
        print_success "Configured $iface for client serving with DHCP subnet 192.168.100.0/24"
    done
else
    print_header "Step 9: Skipping Client Interface Configuration"
    print_info "No client interfaces selected (management only mode)"
fi

# Step 10: Configure iptables
print_header "Step 10: Configuring Firewall"
cat > /etc/iptables.rules << EOF
*nat
:PREROUTING ACCEPT [0:0]
:INPUT ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
:POSTROUTING ACCEPT [0:0]
-A POSTROUTING -o $WAN_INTERFACE -j MASQUERADE
COMMIT

*filter
:INPUT ACCEPT [0:0]
:FORWARD ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
-A FORWARD -i $WAN_INTERFACE -o $MANAGEMENT_INTERFACE -m state --state RELATED,ESTABLISHED -j ACCEPT
-A FORWARD -i $MANAGEMENT_INTERFACE -o $WAN_INTERFACE -j ACCEPT
EOF

# Add rules for client interfaces
for iface in "${CLIENT_INTERFACES[@]}"; do
    cat >> /etc/iptables.rules << EOF
-A FORWARD -i $WAN_INTERFACE -o $iface -m state --state RELATED,ESTABLISHED -j ACCEPT
-A FORWARD -i $iface -o $WAN_INTERFACE -j ACCEPT
EOF
done

cat >> /etc/iptables.rules << EOF
COMMIT
EOF

# Apply iptables rules (suppress errors if modules not loaded)
iptables-restore < /etc/iptables.rules 2>/dev/null || print_warning "iptables rules saved but not applied (will apply on reboot)"
print_success "Firewall configured"

# Step 11: Create systemd services
print_header "Step 11: Creating Systemd Services"

# Management Agent Service
cat > /etc/systemd/system/crowdsurfer-management.service << EOF
[Unit]
Description=CrowdSurfer Management Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/edge
Environment="CROWDSURFER_BACKEND_URL=$BACKEND_URL"
Environment="CROWDSURFER_WAN_INTERFACE=$WAN_INTERFACE"
Environment="CROWDSURFER_MANAGEMENT_INTERFACE=$MANAGEMENT_INTERFACE"
ExecStart=$INSTALL_DIR/edge/venv/bin/python3 management_agent.py
Restart=always
RestartSec=10
StandardOutput=append:$LOG_DIR/management.log
StandardError=append:$LOG_DIR/management.error.log

[Install]
WantedBy=multi-user.target
EOF

# Telemetry Agent Service
cat > /etc/systemd/system/crowdsurfer-telemetry.service << EOF
[Unit]
Description=CrowdSurfer Telemetry Agent
After=network.target crowdsurfer-management.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/edge
Environment="CROWDSURFER_BACKEND_URL=$BACKEND_URL"
ExecStart=$INSTALL_DIR/edge/venv/bin/python3 telemetry_agent.py
Restart=always
RestartSec=10
StandardOutput=append:$LOG_DIR/telemetry.log
StandardError=append:$LOG_DIR/telemetry.error.log

[Install]
WantedBy=multi-user.target
EOF

# Portal Handler Service
cat > /etc/systemd/system/crowdsurfer-portal.service << EOF
[Unit]
Description=CrowdSurfer Portal Handler
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/edge
Environment="CROWDSURFER_BACKEND_URL=$BACKEND_URL"
ExecStart=$INSTALL_DIR/edge/venv/bin/python3 -c "from portal_handler import main; main()"
Restart=always
RestartSec=10
StandardOutput=append:$LOG_DIR/portal.log
StandardError=append:$LOG_DIR/portal.error.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
print_success "Systemd services created"

# Step 12: Enable services
print_header "Step 12: Enabling Services"

# Unmask hostapd and dnsmasq if they're masked
systemctl unmask hostapd 2>/dev/null || true
systemctl unmask dnsmasq 2>/dev/null || true

systemctl enable hostapd 2>/dev/null || print_warning "Could not enable hostapd (will try to start manually)"
systemctl enable dnsmasq 2>/dev/null || print_warning "Could not enable dnsmasq (will try to start manually)"
# Note: nodogsplash not installed, captive portal handled by portal_handler.py
systemctl enable crowdsurfer-management 2>/dev/null || print_warning "Could not enable crowdsurfer-management"
systemctl enable crowdsurfer-telemetry 2>/dev/null || print_warning "Could not enable crowdsurfer-telemetry"
systemctl enable crowdsurfer-portal 2>/dev/null || print_warning "Could not enable crowdsurfer-portal"
print_success "Services enabled"

# Step 13: Create helper scripts
print_header "Step 13: Creating Helper Scripts"

# Status check script
cat > /usr/local/bin/crowdsurfer-status << 'EOFSTATUS'
#!/bin/bash
echo "CrowdSurfer Edge Device Status"
echo "==============================="
echo ""
echo "Services:"
systemctl status crowdsurfer-management --no-pager | grep "Active:"
systemctl status crowdsurfer-telemetry --no-pager | grep "Active:"
systemctl status crowdsurfer-portal --no-pager | grep "Active:"
systemctl status hostapd --no-pager | grep "Active:"
systemctl status dnsmasq --no-pager | grep "Active:"
echo ""
echo "Device Configuration:"
if [ -f /etc/crowdsurfer/device.conf ]; then
    echo "  Device registered: YES"
    python3 -c "import json; data=json.load(open('/etc/crowdsurfer/device.conf')); print(f\"  Serial: {data.get('device_serial', 'N/A')}\"); print(f\"  Token: {data.get('device_token', 'N/A')[:20]}...\" if data.get('device_token') else '  Token: None')"
else
    echo "  Device registered: NO"
fi
echo ""
echo "Network Configuration:"
if [ -f /etc/crowdsurfer/network.conf ]; then
    python3 -c "import json; data=json.load(open('/etc/crowdsurfer/network.conf')); print(f\"  WAN Interface: {data.get('wan_interface', 'N/A')}\"); print(f\"  Management Interface: {data.get('management_interface', 'N/A')}\"); print(f\"  Client Interfaces: {', '.join(data.get('client_interfaces', [])) or 'None'}\")"
else
    echo "  Network configuration: NOT FOUND"
fi
echo ""
echo "Network Status:"
for iface in $(ls /sys/class/net/ | grep -v lo); do
    status=$(ip link show "$iface" | grep -o "state [A-Z]*" | awk '{print $2}')
    ip=$(ip addr show "$iface" | grep "inet " | awk '{print $2}' | head -n1)
    echo "  $iface: $status ${ip:+($ip)}"
done
echo ""
echo "Logs:"
echo "  Management: tail -f /var/log/crowdsurfer/management.log"
echo "  Telemetry: tail -f /var/log/crowdsurfer/telemetry.log"
echo "  Portal: tail -f /var/log/crowdsurfer/portal.log"
EOFSTATUS
chmod +x /usr/local/bin/crowdsurfer-status

# Restart script
cat > /usr/local/bin/crowdsurfer-restart << 'EOF'
#!/bin/bash
echo "Restarting CrowdSurfer services..."
systemctl restart crowdsurfer-management
systemctl restart crowdsurfer-telemetry
systemctl restart crowdsurfer-portal
echo "Services restarted"
EOF
chmod +x /usr/local/bin/crowdsurfer-restart

# Logs script
cat > /usr/local/bin/crowdsurfer-logs << 'EOF'
#!/bin/bash
if [ -z "$1" ]; then
    echo "Usage: crowdsurfer-logs [management|telemetry|portal|all]"
    exit 1
fi

case "$1" in
    management)
        tail -f /var/log/crowdsurfer/management.log
        ;;
    telemetry)
        tail -f /var/log/crowdsurfer/telemetry.log
        ;;
    portal)
        tail -f /var/log/crowdsurfer/portal.log
        ;;
    all)
        tail -f /var/log/crowdsurfer/*.log
        ;;
    *)
        echo "Unknown service: $1"
        exit 1
        ;;
esac
EOF
chmod +x /usr/local/bin/crowdsurfer-logs

# Network reconfiguration script
cat > /usr/local/bin/crowdsurfer-reconfigure-network << 'EOF'
#!/bin/bash
echo "This will reconfigure network interfaces."
echo "WARNING: This may disrupt connectivity!"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# Re-run the deployment script's network configuration section
bash /opt/crowdsurfer/edge/deploy_to_raspi_v5.sh
EOF
chmod +x /usr/local/bin/crowdsurfer-reconfigure-network

# Heartbeat monitor script (if monitor_heartbeat.py exists)
if [ -f "$INSTALL_DIR/edge/monitor_heartbeat.py" ]; then
    # Convert line endings (in case file was copied from Windows)
    if command -v dos2unix &> /dev/null; then
        dos2unix "$INSTALL_DIR/edge/monitor_heartbeat.py" 2>/dev/null || true
    fi
    cp "$INSTALL_DIR/edge/monitor_heartbeat.py" /usr/local/bin/crowdsurfer-monitor
    chmod +x /usr/local/bin/crowdsurfer-monitor
    print_success "Heartbeat monitor installed"
else
    print_warning "Heartbeat monitor not found (copy edge files to install)"
fi

# Step 14: Create Login Banner (MOTD)
print_header "Step 14: Creating Login Banner"

cat > /etc/motd << 'EOFMOTD'
╔══════════════════════════════════════════════════════════════════════════════╗
║                     CrowdSurfer Edge Device - Shaka                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

EOFMOTD

# Add dynamic content
cat >> /etc/motd << EOF
  Deployment Script: v${SCRIPT_VERSION}
  Hostname: $(hostname)
  Backend: $BACKEND_URL

Quick Commands:
  crowdsurfer-status    - Check service status and device info
  crowdsurfer-monitor   - Monitor heartbeats in real-time (sudo required)
  crowdsurfer-restart   - Restart all services
  crowdsurfer-logs all  - View all logs

Management WiFi:
  SSID: CrowdSurfer-Admin
  Password: crowdsurfer2024
  Admin Page: http://10.0.0.1

For help: cat /opt/crowdsurfer/edge/README.md

EOF

print_success "Login banner created"

# Step 15: Final Configuration
print_header "Step 15: Final Configuration"

# Enable IP forwarding
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p

# Set hostname
SERIAL=$(cat /proc/cpuinfo | grep Serial | cut -d ' ' -f 2 | tail -c 4)
NEW_HOSTNAME="crowdsurfer-$SERIAL"
hostnamectl set-hostname "$NEW_HOSTNAME"
print_success "Hostname set to $NEW_HOSTNAME"

# Step 16: Start Services
print_header "Step 16: Starting Services"

print_info "Starting CrowdSurfer services..."
systemctl start crowdsurfer-management 2>/dev/null || print_warning "Could not start crowdsurfer-management"
systemctl start crowdsurfer-telemetry 2>/dev/null || print_warning "Could not start crowdsurfer-telemetry"
systemctl start crowdsurfer-portal 2>/dev/null || print_warning "Could not start crowdsurfer-portal"

# Give services a moment to start
sleep 2

# Check service status
if systemctl is-active --quiet crowdsurfer-management && systemctl is-active --quiet crowdsurfer-telemetry; then
    print_success "Services started successfully"
else
    print_warning "Some services may not have started. Check status after reboot."
fi

# Step 17: Installation Summary
print_header "Installation Complete!"
echo ""
print_success "CrowdSurfer edge device software installed successfully"
echo ""
echo "Device Information:"
echo "  Hostname: $NEW_HOSTNAME"
echo "  Serial: CS-SHAKA-V1-$SERIAL"
echo "  Backend URL: $BACKEND_URL"
echo "  Script Version: v${SCRIPT_VERSION}"
echo ""
echo "Network Configuration:"
echo "  WAN Interface: $WAN_INTERFACE"
echo "  Management Interface: $MANAGEMENT_INTERFACE"
if [ ${#CLIENT_INTERFACES[@]} -gt 0 ]; then
    echo "  Client Interfaces: ${CLIENT_INTERFACES[@]}"
else
    echo "  Client Interfaces: None (management only)"
fi
echo ""
echo "Services Status:"
systemctl is-active --quiet crowdsurfer-management && echo "  ✓ Management Agent: Running" || echo "  ✗ Management Agent: Not Running"
systemctl is-active --quiet crowdsurfer-telemetry && echo "  ✓ Telemetry Agent: Running" || echo "  ✗ Telemetry Agent: Not Running"
systemctl is-active --quiet crowdsurfer-portal && echo "  ✓ Portal Handler: Running" || echo "  ✗ Portal Handler: Not Running"
echo ""
echo "Quick Commands:"
echo "  crowdsurfer-status    - Check service status"
echo "  crowdsurfer-monitor   - Monitor heartbeats"
echo "  crowdsurfer-restart   - Restart all services"
echo "  crowdsurfer-logs all  - View all logs"
echo ""
echo "Management WiFi:"
echo "  SSID: CrowdSurfer-Admin"
echo "  Password: crowdsurfer2024"
echo "  IP: 10.0.0.1"
echo "  Admin Page: http://10.0.0.1"
echo ""
print_warning "IMPORTANT: Reboot required for network configuration to take full effect"
echo ""
print_info "System will reboot in 10 seconds..."
print_info "Press Ctrl+C to cancel reboot"
echo ""

# 10-second countdown with auto-reboot
for i in {10..1}; do
    echo -ne "\rRebooting in $i seconds... "
    sleep 1
done
echo ""
echo ""
print_info "Rebooting now..."
sleep 1
reboot
