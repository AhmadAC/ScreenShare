#!/bin/bash

# Resolve the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Ensure Go, Node/Deno, and local paths are included in PATH
export PATH="$HOME/.local/go/bin:$HOME/go/bin:$HOME/.deno/bin:$PATH"

# Locate Python environment
PYTHON_BIN="$HOME/.local/server-venv/bin/python3"
if [ ! -f "$PYTHON_BIN" ]; then
    if [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
        PYTHON_BIN="$SCRIPT_DIR/venv/bin/python3"
    else
        PYTHON_BIN="$(which python3 2>/dev/null || echo "python3")"
    fi
fi

BUILD_REQUESTED=false
PACKAGE_REQUESTED=false

for arg in "$@"; do
    case $arg in
        --build|-b|build)
            BUILD_REQUESTED=true
            ;;
        --package|-p|package)
            BUILD_REQUESTED=true
            PACKAGE_REQUESTED=true
            ;;
        --help|-h)
            echo "Usage: ./start.sh [options]"
            echo "Options:"
            echo "  (no args)       Start the Screego application (auto-builds binary if missing)"
            echo "  --build, -b     Rebuild the React frontend and Go binary before starting"
            echo "  --package, -p   Rebuild and package into standalone bundle using PyInstaller"
            echo "  --help, -h      Show this help message"
            exit 0
            ;;
    esac
done

# Check if precompiled Go binary or UI build directory is missing
if [ ! -f "$SCRIPT_DIR/screego" ] || [ ! -d "$SCRIPT_DIR/ui/build" ]; then
    BUILD_REQUESTED=true
fi

# 1. Build Frontend and Go Binary if requested or missing
if [ "$BUILD_REQUESTED" = "true" ]; then
    echo "=========================================="
    echo " Building Screego Application Assets"
    echo "=========================================="
    
    if [ -d "ui" ]; then
        echo "[1/2] Building React UI..."
        cd ui
        if command -v deno &>/dev/null; then
            deno install
            deno task build
        elif command -v yarn &>/dev/null; then
            yarn
            yarn build
        elif command -v npm &>/dev/null; then
            npm install
            npm run build
        else
            echo "Error: Neither deno, yarn, nor npm was found to build the frontend."
            exit 1
        fi
        cd "$SCRIPT_DIR"
    fi

    echo "[2/2] Compiling standalone Go binary (screego)..."
    if command -v go &>/dev/null; then
        export CGO_ENABLED=0
        go build -ldflags="-s -w -X main.mode=prod" -o screego .
    else
        echo "Error: 'go' compiler is not installed or not in PATH."
        exit 1
    fi
    echo "Binary compilation finished successfully."
    echo "=========================================="
fi

# 2. Package into a PyInstaller standalone bundle if requested
if [ "$PACKAGE_REQUESTED" = "true" ]; then
    echo "Packaging into a self-contained standalone executable..."
    if command -v pyinstaller &>/dev/null || $PYTHON_BIN -m PyInstaller --version &>/dev/null; then
        PYINSTALLER_CMD="pyinstaller"
        if ! command -v pyinstaller &>/dev/null; then
            PYINSTALLER_CMD="$PYTHON_BIN -m PyInstaller"
        fi
        
        $PYINSTALLER_CMD --noconfirm --onedir --windowed \
            --name "screego-host" \
            --add-binary "screego:." \
            --add-data "users:." \
            control_server.py
            
        echo "=========================================="
        echo " Packaging complete!"
        echo " Standalone bundle: $SCRIPT_DIR/dist/screego-host/screego-host"
        echo " You can distribute the 'dist/screego-host' folder to any host without Go/Python installed."
        echo "=========================================="
        exit 0
    else
        echo "Error: PyInstaller is not installed in the current Python environment."
        echo "Install it with: $PYTHON_BIN -m pip install pyinstaller"
        exit 1
    fi
fi

# 3. Launch via Standalone Bundle or Python Controller
if [ -f "$SCRIPT_DIR/dist/screego-host/screego-host" ] && [ "$BUILD_REQUESTED" = "false" ]; then
    echo "Starting prepackaged standalone binary: dist/screego-host/screego-host"
    exec "$SCRIPT_DIR/dist/screego-host/screego-host"
else
    echo "Starting Screego Controller..."
    exec "$PYTHON_BIN" "$SCRIPT_DIR/control_server.py"
fi