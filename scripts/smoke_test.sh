#!/usr/bin/env bash
set -e

echo "Starting package smoke test..."

# 1. Ensure dist directory exists and has a wheel
if [ ! -d "dist" ] || [ -z "$(ls -A dist/*.whl 2>/dev/null)" ]; then
    echo "No .whl found in dist/. Building..."
    uv run python -m build
fi

WHEEL_FILE=$(ls dist/*.whl | head -n 1)
echo "Found wheel: $WHEEL_FILE"

# 2. Create a temporary project directory
TMP_PROJECT=$(mktemp -d)
echo "Created temporary project at $TMP_PROJECT"

# Ensure cleanup on exit
trap 'rm -rf "$TMP_PROJECT"' EXIT

cd "$TMP_PROJECT"

# 3. Create an isolated virtualenv
uv venv .venv
source .venv/bin/activate

# 4. Install the packed tarball/wheel
echo "Installing package..."
uv pip install "$OLDPWD/$WHEEL_FILE"

# 5. Import the library
echo "Testing import compatibility..."
uv run python -c "import autoweave; print('Successfully imported autoweave!')"

# 6. Run a minimal real usage example (CLI)
echo "Testing CLI..."
autoweave --help > /dev/null

echo "✅ Smoke test completed successfully. The package is healthy."
