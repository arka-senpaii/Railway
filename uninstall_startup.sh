#!/bin/bash

# Color codes
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

echo -e "${CYAN}${BOLD}>>> Smart Railway Service Uninstaller <<<${NC}\n"

SERVICE_FILE="/etc/systemd/system/smart-railway.service"

echo -e "${YELLOW}[1] Stopping Smart Railway service...${NC}"
# Stop the service if it is running
sudo systemctl stop smart-railway.service 2>/dev/null || true

echo -e "${YELLOW}[2] Disabling service from startup...${NC}"
# Disable the service so it doesn't run on boot
sudo systemctl disable smart-railway.service 2>/dev/null || true

echo -e "${YELLOW}[3] Removing systemd service file...${NC}"
if [ -f "$SERVICE_FILE" ]; then
    sudo rm "$SERVICE_FILE"
    echo -e "${GREEN}[✓] Service file removed.${NC}"
else
    echo -e "${YELLOW}[!] Service file not found. Skipping.${NC}"
fi

echo -e "${YELLOW}[4] Reloading systemd daemon...${NC}"
sudo systemctl daemon-reload

echo -e "\n${GREEN}${BOLD}>>> UNINSTALLATION COMPLETE <<<${NC}"
echo -e "The Smart Railway Controller autorun has been stopped and disabled."
