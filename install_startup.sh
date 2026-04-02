#!/bin/bash

# Color codes
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
BOLD='\033[1m'

echo -e "${CYAN}${BOLD}>>> Smart Railway Service Installer <<<${NC}\n"

# Get correct user even if running via sudo
if [ -n "$SUDO_USER" ]; then
  ACTUAL_USER=$SUDO_USER
else
  ACTUAL_USER=$USER
fi

# Get current script path
cd "$(dirname "$0")"
PROJECT_DIR=$(pwd)
SERVICE_FILE="/etc/systemd/system/smart-railway.service"

echo -e "${YELLOW}[0] Making autorun script executable...${NC}"
chmod +x "$PROJECT_DIR/autorun.sh"

echo -e "${YELLOW}[1] Generating systemd service file...${NC}"

# Create the service file dynamically based on the current location
cat << EOF | sudo tee $SERVICE_FILE > /dev/null
[Unit]
Description=Smart Railway Automated Protocol Server
After=network-online.target
Wants=network-online.target

[Service]
# Execute the OP autorun script
ExecStart=/bin/bash $PROJECT_DIR/autorun.sh
WorkingDirectory=$PROJECT_DIR
StandardOutput=inherit
StandardError=inherit
Restart=always
RestartSec=10
# Assumes running as the default pi user. Resolves safely even inside sudo.
User=$ACTUAL_USER

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}[✓] Service file generated at $SERVICE_FILE${NC}"

echo -e "${YELLOW}[2] Reloading systemd daemon...${NC}"
sudo systemctl daemon-reload

echo -e "${YELLOW}[3] Enabling service to run on startup...${NC}"
sudo systemctl enable smart-railway.service

echo -e "${YELLOW}[4] Starting Smart Railway service now...${NC}"
sudo systemctl start smart-railway.service

echo -e "\n${GREEN}${BOLD}>>> INSTALLATION COMPLETE <<<${NC}"
echo -e "The Smart Railway Controller will now automatically boot up every time your Raspberry Pi turns on!"
echo -e "To check the background status, use: ${CYAN}sudo systemctl status smart-railway.service${NC}"
