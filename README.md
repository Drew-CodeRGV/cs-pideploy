# CrowdSurfer Pi Bootstrap

Public bootstrap for CrowdSurfer edge devices.

## Quick Start

```bash
curl -sSL https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/install.sh | sudo bash
```

## What This Script Does

### Stage 1: Bootstrap (Public)
1. Installs minimal dependencies (Python, curl, jq)
2. Creates bootstrap agent
3. Registers device with backend using serial number
4. Waits for admin authorization

### Stage 2: Deployment (After Authorization)
1. Admin authorizes device in CrowdSurfer admin panel
2. Bootstrap agent receives authorization token
3. Downloads full edge system from backend
4. Installs complete CrowdSurfer edge system
5. Starts all services

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Stage 1: Public Bootstrap (cs-pideploy repo)               │
├─────────────────────────────────────────────────────────────┤
│ • Minimal install script (publicly accessible)              │
│ • Basic dependencies only                                   │
│ • Device registration                                       │
│ • NO proprietary code                                       │
└─────────────────────────────────────────────────────────────┘
                            ↓
                    Device registers
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Admin Authorization (CrowdSurfer Admin Panel)               │
├─────────────────────────────────────────────────────────────┤
│ • Admin sees new device in pending list                     │
│ • Admin authorizes device                                   │
│ • Backend issues device token                               │
└─────────────────────────────────────────────────────────────┘
                            ↓
                    Token delivered to Pi
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Stage 2: Secure Deployment (from backend)                  │
├─────────────────────────────────────────────────────────────┤
│ • Pi downloads deployment package from backend              │
│ • Package contains full edge system code                    │
│ • Proprietary code stays private                            │
│ • Full installation completes automatically                 │
└─────────────────────────────────────────────────────────────┘
```

## Security Benefits

### IP Protection
- ✅ Proprietary code not exposed publicly
- ✅ Full edge system only delivered to authorized devices
- ✅ Deployment package served over HTTPS with authentication

### Access Control
- ✅ Admin must explicitly authorize each device
- ✅ Unauthorized devices cannot download code
- ✅ Token-based authentication for deployment

### Audit Trail
- ✅ All device registrations logged
- ✅ Authorization events tracked
- ✅ Deployment downloads recorded

## What Gets Installed

### Stage 1 (Public Bootstrap)
- Python 3 + pip + venv
- curl, jq
- Bootstrap agent (~100 lines)
- Systemd service for bootstrap

### Stage 2 (After Authorization)
- Full edge system:
  - Telemetry agent
  - Management agent
  - Portal handler
  - Local admin server
  - LED controller
  - Structured logger
  - Connectivity monitor
  - Queue manager
- WiFi AP configuration (hostapd, dnsmasq)
- Captive portal (nodogsplash)
- All systemd services
- Helper scripts

## Monitoring Bootstrap Progress

```bash
# Watch bootstrap log
tail -f /var/log/crowdsurfer/bootstrap.log

# Check bootstrap service status
systemctl status crowdsurfer-bootstrap

# Check if device is authorized
cat /etc/crowdsurfer/device.conf
```

## For Technicians

### Installation Steps
1. Flash Raspberry Pi OS to SD card
2. Boot Raspberry Pi
3. Connect to internet (Ethernet or WiFi)
4. Run bootstrap command (see Quick Start above)
5. Wait for "Waiting for authorization..." message
6. Notify admin to authorize device
7. Wait for automatic installation to complete
8. Access admin interface at http://10.0.0.1:8080

### Troubleshooting

**Device not registering:**
- Check internet connection
- Verify backend URL is accessible
- Check bootstrap log for errors

**Authorization timeout:**
- Confirm admin has authorized device in admin panel
- Check device serial number matches
- Restart bootstrap service: `systemctl restart crowdsurfer-bootstrap`

**Deployment download fails:**
- Verify device token is valid
- Check backend is accessible
- Check disk space: `df -h`

## Environment Variables

```bash
# Custom backend URL (default: https://crowdsurfer.politiquera.com)
export CROWDSURFER_BACKEND_URL="https://your-backend.com"

# Then run bootstrap
curl -sSL https://raw.githubusercontent.com/Drew-CodeRGV/cs-pideploy/main/install.sh | sudo bash
```

## Repository Structure

```
cs-pideploy/
├── install.sh          # Bootstrap installation script
├── README.md           # This file
└── LICENSE             # MIT License
```

## Support

For issues or questions:
- Email: support@crowdsurfer.com
- Documentation: https://docs.crowdsurfer.com
- Admin Panel: https://crowdsurfer.politiquera.com

## License

MIT License - See LICENSE file for details

---

**Note**: This is the public bootstrap repository. The full CrowdSurfer edge system code is proprietary and delivered securely after device authorization.
