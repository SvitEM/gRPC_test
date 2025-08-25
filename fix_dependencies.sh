#!/bin/bash
# Script to fix protobuf dependency conflicts
set -e

echo "🔧 Fixing protobuf dependency conflicts..."

# Uninstall conflicting packages
echo "📦 Uninstalling conflicting packages..."
pip uninstall -y protobuf grpcio grpcio-tools || true

# Clear pip cache to avoid cached incompatible versions
echo "🧹 Clearing pip cache..."
pip cache purge

# Reinstall with correct versions
echo "📦 Installing compatible protobuf version..."
pip install "protobuf>=4.21.0,<5.0.0"

echo "📦 Installing gRPC packages..."
pip install "grpcio>=1.60.0"
pip install "grpcio-tools>=1.60.0"

echo "📦 Installing other dependencies..."
pip install "python-dotenv>=1.0.0"

# Verify installation
echo ""
echo "✅ Verifying installation..."
python3 -c "
import grpc
import google.protobuf
print(f'grpcio: {grpc.__version__}')
print(f'protobuf: {google.protobuf.__version__}')
"

echo ""
echo "🔍 Checking for conflicts..."
pip check || echo "⚠️  Some conflicts may remain - check if they affect your specific use case"

echo ""
echo "🎉 Dependencies fixed! You can now:"
echo "  1. Regenerate protobuf stubs: ./setup.sh"
echo "  2. Run tests: python3 test_server_simple.py &"
echo "  3. Test client: python3 test_insecure_steady.py"