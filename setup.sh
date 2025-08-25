#!/bin/bash
# Setup script for gRPC Latency Tests
set -e

echo "🚀 Setting up gRPC Latency Tests..."

# Check Python version
echo "📋 Checking Python version..."
python_version=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1-2)
required_version="3.11"

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)"; then
    echo "❌ Python 3.11+ required. Found: $(python3 --version)"
    echo "   Please install Python 3.11 or higher"
    exit 1
fi
echo "✅ Python version OK: $(python3 --version)"

# Install dependencies
echo "📦 Installing Python dependencies..."
pip3 install -r requirements.txt

echo "🔧 Installing development dependencies..."
pip3 install -r requirements-dev.txt

# Generate protobuf stubs
echo "🔨 Generating protobuf stubs..."
if [ ! -f "proto/score.proto" ]; then
    echo "❌ proto/score.proto not found!"
    exit 1
fi

# Generate stubs for DF server
echo "   Generating stubs for DF server..."
python3 -m grpc_tools.protoc \
    --proto_path=proto \
    --python_out=df \
    --grpc_python_out=df \
    proto/score.proto

# Generate stubs for SMFT client  
echo "   Generating stubs for SMFT client..."
python3 -m grpc_tools.protoc \
    --proto_path=proto \
    --python_out=smft \
    --grpc_python_out=smft \
    proto/score.proto

echo "✅ Protobuf stubs generated successfully"

# Check if certificates exist
echo "🔐 Checking TLS certificates..."
if [ -f "df/certs/ca.crt" ] && [ -f "df/certs/server.crt" ] && [ -f "smft/certs/client.crt" ]; then
    echo "✅ TLS certificates found"
else
    echo "⚠️  TLS certificates not found. Run generate_certs.sh to create them."
fi

# Create results directory if it doesn't exist
echo "📁 Creating results directory..."
mkdir -p results

echo ""
echo "🎉 Setup complete! You can now run the tests:"
echo ""
echo "Quick test (insecure):"
echo "  python3 test_server_simple.py &"
echo "  N_RPS=10 T_DURATION_SEC=5 python3 test_insecure_steady.py"
echo ""
echo "Full test (with TLS):"
echo "  cd df && python3 01_steady_server.py &"
echo "  cd smft && N_RPS=100 T_DURATION_SEC=30 python3 01_steady_client.py"
echo ""
echo "Analyze results:"
echo "  python3 tools/summarize.py 01_steady_results.txt"
echo ""
echo "📖 See README_RU.md for detailed instructions in Russian"
echo "📖 See README.md for detailed instructions in English"