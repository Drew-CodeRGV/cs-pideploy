"""
Local Admin Server for CrowdSurfer Edge Devices

Provides a web interface accessible via the management WiFi network
for local device configuration and monitoring.

Access at: http://10.0.0.1:8080
"""

from flask import Flask, render_template_string, request, jsonify
import json
import subprocess
import os
import logging
from pathlib import Path
from typing import Dict, Any, List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration paths
CONFIG_DIR = Path("/etc/crowdsurfer")
NETWORK_CONF = CONFIG_DIR / "network.conf"
DEVICE_CONF = CONFIG_DIR / "device.conf"

# HTML Template for admin page
ADMIN_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CrowdSurfer Device Admin</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
        }
        
        .card {
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        
        h1 {
            color: #667eea;
            margin-bottom: 10px;
            font-size: 32px;
        }
        
        h2 {
            color: #333;
            margin-bottom: 20px;
            font-size: 24px;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }
        
        .subtitle {
            color: #666;
            margin-bottom: 30px;
        }
        
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .status-item {
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        
        .status-label {
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 5px;
        }
        
        .status-value {
            font-size: 18px;
            font-weight: 600;
            color: #333;
        }
        
        .status-online {
            color: #28a745;
        }
        
        .status-offline {
            color: #dc3545;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #333;
        }
        
        select, input[type="text"] {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        
        select:focus, input[type="text"]:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .checkbox-group {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        
        .checkbox-item {
            display: flex;
            align-items: center;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        
        .checkbox-item input[type="checkbox"] {
            width: 20px;
            height: 20px;
            margin-right: 10px;
        }
        
        .checkbox-item label {
            margin: 0;
            font-weight: normal;
        }
        
        button {
            background: #667eea;
            color: white;
            border: none;
            padding: 14px 28px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.3s;
        }
        
        button:hover {
            background: #5568d3;
        }
        
        button:disabled {
            background: #ccc;
            cursor: not-allowed;
        }
        
        .button-group {
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }
        
        .alert {
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        
        .alert-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        
        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        .alert-warning {
            background: #fff3cd;
            color: #856404;
            border: 1px solid #ffeaa7;
        }
        
        .interface-badge {
            display: inline-block;
            padding: 4px 12px;
            background: #667eea;
            color: white;
            border-radius: 20px;
            font-size: 14px;
            margin-right: 8px;
            margin-bottom: 8px;
        }
        
        .help-text {
            font-size: 14px;
            color: #666;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1>🌊 CrowdSurfer Device Admin</h1>
            <p class="subtitle">Local device configuration and monitoring</p>
            
            <div id="alert-container"></div>
            
            <h2>Device Status</h2>
            <div class="status-grid">
                <div class="status-item">
                    <div class="status-label">Device Serial</div>
                    <div class="status-value" id="device-serial">Loading...</div>
                </div>
                <div class="status-item">
                    <div class="status-label">Connection Status</div>
                    <div class="status-value" id="connection-status">Loading...</div>
                </div>
                <div class="status-item">
                    <div class="status-label">Backend URL</div>
                    <div class="status-value" id="backend-url">Loading...</div>
                </div>
                <div class="status-item">
                    <div class="status-label">Last Heartbeat</div>
                    <div class="status-value" id="last-heartbeat">Loading...</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>Network Configuration</h2>
            
            <div class="form-group">
                <label for="wan-interface">WAN Interface (Internet Connection)</label>
                <select id="wan-interface">
                    <option value="">Loading...</option>
                </select>
                <p class="help-text">Select the interface that connects to the internet (typically eth0 or wlan1)</p>
            </div>
            
            <div class="form-group">
                <label for="management-interface">Management Interface (Admin WiFi)</label>
                <select id="management-interface">
                    <option value="">Loading...</option>
                </select>
                <p class="help-text">Select the interface for the management WiFi network (typically wlan0)</p>
            </div>
            
            <div class="form-group">
                <label>Client Interfaces (Serve WiFi to Attendees)</label>
                <div class="checkbox-group" id="client-interfaces">
                    <p>Loading...</p>
                </div>
                <p class="help-text">Select interfaces that should serve WiFi to event attendees (e.g., USB WiFi adapters)</p>
            </div>
            
            <div class="button-group">
                <button onclick="saveNetworkConfig()">Save Configuration</button>
                <button onclick="restartServices()">Restart Services</button>
            </div>
        </div>
        
        <div class="card">
            <h2>Current Network Interfaces</h2>
            <div id="interface-list">Loading...</div>
        </div>
    </div>
    
    <script>
        // Load device status
        async function loadDeviceStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                
                document.getElementById('device-serial').textContent = data.device_serial || 'Not registered';
                document.getElementById('connection-status').textContent = data.registered ? 'Registered' : 'Not registered';
                document.getElementById('connection-status').className = 'status-value ' + (data.registered ? 'status-online' : 'status-offline');
                document.getElementById('backend-url').textContent = data.backend_url || 'N/A';
                document.getElementById('last-heartbeat').textContent = data.last_heartbeat || 'Never';
            } catch (error) {
                console.error('Error loading device status:', error);
            }
        }
        
        // Load network interfaces
        async function loadNetworkInterfaces() {
            try {
                const response = await fetch('/api/interfaces');
                const data = await response.json();
                
                // Populate WAN interface dropdown
                const wanSelect = document.getElementById('wan-interface');
                wanSelect.innerHTML = data.interfaces.map(iface => 
                    `<option value="${iface.name}" ${iface.name === data.current.wan_interface ? 'selected' : ''}>
                        ${iface.name} - ${iface.status} ${iface.ip ? '(' + iface.ip + ')' : ''}
                    </option>`
                ).join('');
                
                // Populate management interface dropdown
                const mgmtSelect = document.getElementById('management-interface');
                mgmtSelect.innerHTML = data.interfaces.map(iface => 
                    `<option value="${iface.name}" ${iface.name === data.current.management_interface ? 'selected' : ''}>
                        ${iface.name} - ${iface.status} ${iface.ip ? '(' + iface.ip + ')' : ''}
                    </option>`
                ).join('');
                
                // Populate client interfaces checkboxes
                const clientDiv = document.getElementById('client-interfaces');
                clientDiv.innerHTML = data.interfaces.map(iface => 
                    `<div class="checkbox-item">
                        <input type="checkbox" id="client-${iface.name}" value="${iface.name}" 
                            ${data.current.client_interfaces.includes(iface.name) ? 'checked' : ''}>
                        <label for="client-${iface.name}">
                            ${iface.name} - ${iface.status} ${iface.ip ? '(' + iface.ip + ')' : ''}
                        </label>
                    </div>`
                ).join('');
                
                // Display interface list
                const interfaceList = document.getElementById('interface-list');
                interfaceList.innerHTML = data.interfaces.map(iface => 
                    `<div class="status-item">
                        <div class="status-label">${iface.name}</div>
                        <div class="status-value">${iface.status} ${iface.ip ? '- ' + iface.ip : ''}</div>
                    </div>`
                ).join('');
            } catch (error) {
                console.error('Error loading network interfaces:', error);
            }
        }
        
        // Save network configuration
        async function saveNetworkConfig() {
            const wanInterface = document.getElementById('wan-interface').value;
            const managementInterface = document.getElementById('management-interface').value;
            const clientInterfaces = Array.from(document.querySelectorAll('#client-interfaces input[type="checkbox"]:checked'))
                .map(cb => cb.value);
            
            try {
                const response = await fetch('/api/network-config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        wan_interface: wanInterface,
                        management_interface: managementInterface,
                        client_interfaces: clientInterfaces
                    })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    showAlert('Configuration saved successfully! Restart services to apply changes.', 'success');
                } else {
                    showAlert('Error saving configuration: ' + data.error, 'error');
                }
            } catch (error) {
                showAlert('Error saving configuration: ' + error.message, 'error');
            }
        }
        
        // Restart services
        async function restartServices() {
            if (!confirm('This will restart all CrowdSurfer services. Continue?')) {
                return;
            }
            
            try {
                const response = await fetch('/api/restart', {
                    method: 'POST'
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    showAlert('Services restarted successfully!', 'success');
                } else {
                    showAlert('Error restarting services: ' + data.error, 'error');
                }
            } catch (error) {
                showAlert('Error restarting services: ' + error.message, 'error');
            }
        }
        
        // Show alert message
        function showAlert(message, type) {
            const alertContainer = document.getElementById('alert-container');
            const alertClass = type === 'success' ? 'alert-success' : 'alert-error';
            alertContainer.innerHTML = `<div class="alert ${alertClass}">${message}</div>`;
            
            setTimeout(() => {
                alertContainer.innerHTML = '';
            }, 5000);
        }
        
        // Load data on page load
        window.addEventListener('load', () => {
            loadDeviceStatus();
            loadNetworkInterfaces();
            
            // Refresh status every 30 seconds
            setInterval(loadDeviceStatus, 30000);
        });
    </script>
</body>
</html>
"""


def get_network_interfaces() -> List[Dict[str, Any]]:
    """Get list of available network interfaces."""
    interfaces = []
    
    try:
        # List all interfaces except loopback
        for iface in os.listdir('/sys/class/net/'):
            if iface == 'lo':
                continue
            
            # Get interface status
            try:
                result = subprocess.run(
                    ['ip', 'link', 'show', iface],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                status = 'UP' if 'state UP' in result.stdout else 'DOWN'
            except:
                status = 'UNKNOWN'
            
            # Get IP address
            ip = None
            try:
                result = subprocess.run(
                    ['ip', 'addr', 'show', iface],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in result.stdout.split('\n'):
                    if 'inet ' in line:
                        ip = line.strip().split()[1]
                        break
            except:
                pass
            
            interfaces.append({
                'name': iface,
                'status': status,
                'ip': ip
            })
    except Exception as e:
        logger.error(f"Error getting network interfaces: {e}")
    
    return interfaces


def get_current_network_config() -> Dict[str, Any]:
    """Get current network configuration."""
    config = {
        'wan_interface': 'eth0',
        'management_interface': 'wlan0',
        'client_interfaces': []
    }
    
    try:
        if NETWORK_CONF.exists():
            with open(NETWORK_CONF, 'r') as f:
                config = json.load(f)
    except Exception as e:
        logger.error(f"Error loading network config: {e}")
    
    return config


def save_network_config(config: Dict[str, Any]) -> bool:
    """Save network configuration."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        with open(NETWORK_CONF, 'w') as f:
            json.dump(config, f, indent=2)
        
        os.chmod(NETWORK_CONF, 0o600)
        
        logger.info(f"Saved network configuration: {config}")
        return True
    except Exception as e:
        logger.error(f"Error saving network config: {e}")
        return False


def get_device_status() -> Dict[str, Any]:
    """Get device status."""
    status = {
        'device_serial': None,
        'registered': False,
        'backend_url': os.getenv('CROWDSURFER_BACKEND_URL', 'https://crowdsurfer.politiquera.com'),
        'last_heartbeat': None
    }
    
    try:
        if DEVICE_CONF.exists():
            with open(DEVICE_CONF, 'r') as f:
                device_config = json.load(f)
                status['device_serial'] = device_config.get('device_serial')
                status['registered'] = device_config.get('device_token') is not None
    except Exception as e:
        logger.error(f"Error loading device config: {e}")
    
    return status


@app.route('/')
def index():
    """Serve the admin page."""
    return render_template_string(ADMIN_PAGE_TEMPLATE)


@app.route('/api/status')
def api_status():
    """Get device status."""
    return jsonify(get_device_status())


@app.route('/api/interfaces')
def api_interfaces():
    """Get network interfaces."""
    return jsonify({
        'interfaces': get_network_interfaces(),
        'current': get_current_network_config()
    })


@app.route('/api/network-config', methods=['POST'])
def api_save_network_config():
    """Save network configuration."""
    try:
        config = request.json
        
        if save_network_config(config):
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Failed to save configuration'}), 500
    except Exception as e:
        logger.error(f"Error in save network config API: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/restart', methods=['POST'])
def api_restart():
    """Restart CrowdSurfer services."""
    try:
        subprocess.run(['systemctl', 'restart', 'crowdsurfer-management'], check=True)
        subprocess.run(['systemctl', 'restart', 'crowdsurfer-telemetry'], check=True)
        subprocess.run(['systemctl', 'restart', 'crowdsurfer-portal'], check=True)
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error restarting services: {e}")
        return jsonify({'error': str(e)}), 500


def main():
    """Main entry point for local admin server."""
    logger.info("Starting CrowdSurfer Local Admin Server...")
    logger.info("Access at: http://10.0.0.1:8080")
    
    app.run(host='0.0.0.0', port=8080, debug=False)


if __name__ == "__main__":
    main()
