#!/usr/bin/env bash
# Runs once when the Codespace is first created.
# Installs SafeSignal in editable mode with dev dependencies.

set -euo pipefail

echo ""
echo "========================================="
echo "  SafeSignal Codespace — Post-Create"
echo "========================================="
echo ""

# Upgrade pip quietly
echo "→ Upgrading pip..."
pip install --upgrade pip --quiet

# Install SafeSignal in editable mode with dev extras
echo "→ Installing SafeSignal (this may take 2–3 min)..."
pip install -e ".[dev]" --quiet

# Create a .env file from the template if one doesn't exist yet
if [ ! -f .env ]; then
    echo "→ Creating .env from .env.example..."
    cp .env.example .env
    echo ""
    echo "⚠️  Edit .env to add your ANTHROPIC_API_KEY before running the pipeline."
fi

# Verify the install worked
echo "→ Verifying install..."
python -c "import safesignal; print(f'  SafeSignal {safesignal.__version__} installed OK')"

echo ""
echo "========================================="
echo "  ✅ Setup complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "  1. Add your Anthropic API key to .env"
echo "     → Click the .env file in the file explorer and edit"
echo "     → Get a key at https://console.anthropic.com"
echo ""
echo "  2. Run the tests (no API cost):"
echo "     → pytest tests/unit -v"
echo ""
echo "  3. Pull real MAUDE data (free, no API cost):"
echo "     → safesignal ingest --product-code QIH --limit 5"
echo ""
echo "  4. Run Claude extraction (~\$0.05 cost):"
echo "     → safesignal extract --product-code QIH --limit 3"
echo ""
echo "See README.md for full documentation."
echo ""
