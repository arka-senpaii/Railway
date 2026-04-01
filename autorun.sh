#!/bin/bash

# ANSI Color Codes
CYAN='\033[0;36m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color
BOLD='\033[1m'

clear
echo -e "${CYAN}${BOLD}"
cat << "EOF"
  ____                      _     ____       _ _                       
 / ___| _ __ ___   __ _ _ __| |_  |  _ \ __ _(_) |_      ____ _ _   _    
 \___ \| '_ ` _ \ / _` | '__| __| | |_) / _` | | \ \ /\ / / _` | | | |   
  ___) | | | | | | (_| | |  | |_  |  _ < (_| | | |\ V  V / (_| | |_| |   
 |____/|_| |_| |_|\__,_|_|   \__| |_| \_\__,_|_|_| \_/\_/ \__,_|\__, |   
                                                                 |___/     
EOF
echo -e "${NC}"
echo -e "${BLUE}========================================================================${NC}"
echo -e "${YELLOW}[SYSTEM]${NC} Initialising Smart Railway Automated Protocol..."
echo -e "${BLUE}========================================================================${NC}\n"

# Change to the directory where the script is located
cd "$(dirname "$0")"
PROJECT_DIR=$(pwd)

# If venv exists but bin/activate doesn't, it's likely a Windows venv copied over. Let's delete it so it builds a clean Linux one.
if [ -d "venv" ] && [ ! -f "venv/bin/activate" ]; then
    echo -e "${RED}[!]${NC} Invalid or Windows venv detected. Cleaning up..."
    rm -rf venv
fi

# Create Python Virtual Environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}[+]${NC} Building Python Sandbox (Virtual Environment)..."
    python3 -m venv venv || {
        echo -e "${RED}[!]${NC} Failed to create venv. Run: sudo apt install python3-full python3-venv"
        exit 1
    }
    echo -e "${GREEN}[✓] Sandbox Initialised.${NC}"
fi

echo -e "${YELLOW}[+]${NC} Injecting Environment Variables..."
source venv/bin/activate
echo -e "${GREEN}[✓] Environment Active.${NC}"

echo -e "${YELLOW}[+]${NC} Synthesizing Dependencies..."
pip install -r raspberry_pi/requirements.txt -q
echo -e "${GREEN}[✓] Modules Loaded.${NC}"

# Initialize Firebase with the 3-field structure
echo -e "${YELLOW}[+]${NC} Uplinking to Firebase (Seeding Gate Status)..."
cd raspberry_pi
python3 run_demo.py
SEED_STATUS=$?
cd "$PROJECT_DIR"
if [ $SEED_STATUS -eq 0 ]; then
    echo -e "${GREEN}[✓] Firebase Uplink Successful.${NC}"
else
    echo -e "${RED}[!] Firebase seed failed — continuing anyway.${NC}"
fi

# Start backend python script in the background
echo -e "${YELLOW}[+]${NC} Engaging Core Hardware Controllers..."
cd raspberry_pi
python3 main.py > "$PROJECT_DIR/railway_core.log" 2>&1 &
CORE_PID=$!
cd "$PROJECT_DIR"
echo -e "${GREEN}[✓] Core Online (PID: $CORE_PID, Logs: railway_core.log).${NC}"

# Serve your web dashboard
echo -e "${YELLOW}[+]${NC} Launching Orbital Dashboard..."

echo -e "\n${GREEN}${BOLD}========================================================================${NC}"
echo -e "${CYAN}${BOLD}                    >>> ALL SYSTEMS NOMINAL <<<${NC}"
echo -e "${GREEN}${BOLD}========================================================================${NC}"
echo -e "Access Live Telemetry on your network at: ${YELLOW}http://<Your-IP>:8000${NC}\n"

# Keep the script alive by launching the server in foreground
cd dashboard
python3 -m http.server 8000
