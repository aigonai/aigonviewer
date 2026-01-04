#!/bin/bash
# Install Aigon Viewer Server as a global uv tool

set -e

echo "📦 Installing Aigon Viewer Server"
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "⚠️  uv not found. Installing uv..."
    echo ""
    curl -LsSf https://astral.sh/uv/install.sh | sh
    echo ""
    echo "✅ uv installed successfully"
    echo ""

    # Source the shell config to get uv in PATH
    if [ -f "$HOME/.cargo/env" ]; then
        source "$HOME/.cargo/env"
    fi

    # Verify uv is now available
    if ! command -v uv &> /dev/null; then
        echo "❌ uv installation failed. Please install manually:"
        echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
fi

echo "📥 Installing aigonviewer..."
echo ""

# Install or update the tool
uv tool install --force .

echo ""
echo "✅ Installation complete!"
echo ""
echo "To run the server:"
echo "   aigonviewer ~/notes"
echo ""
echo "For help:"
echo "   aigonviewer --help"
