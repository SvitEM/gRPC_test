#!/bin/bash
# Setup script for protobuf 6.x in clean virtual environment
set -e

echo "🚀 Setting up gRPC project with protobuf 6.x..."

# Create virtual environment
echo "📦 Creating virtual environment..."
python3.11 -m venv venv_protobuf6
source venv_protobuf6/bin/activate

echo "✅ Virtual environment created and activated"

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip

# Install protobuf 6.x first
echo "📦 Installing protobuf 6.x..."
pip install "protobuf>=6.0.0"

# Install gRPC packages
echo "📦 Installing gRPC packages..."
pip install "grpcio>=1.60.0"
pip install "grpcio-tools>=1.60.0"

# Install other dependencies
echo "📦 Installing other dependencies..."
pip install "python-dotenv>=1.0.0"

# Verify versions
echo ""
echo "✅ Installed versions:"
python -c "
import grpc
import google.protobuf
print(f'grpcio: {grpc.__version__}')
print(f'protobuf: {google.protobuf.__version__}')
print(f'Python: {__import__(\"sys\").version.split()[0]}')
"

# Generate protobuf stubs with new version
echo ""
echo "🔨 Regenerating protobuf stubs with protobuf 6.x..."

# Clean old stubs
rm -f df/score_pb2*.py smft/score_pb2*.py

# Generate new stubs
python -m grpc_tools.protoc --proto_path=proto --python_out=df --grpc_python_out=df proto/score.proto
python -m grpc_tools.protoc --proto_path=proto --python_out=smft --grpc_python_out=smft proto/score.proto

echo "✅ Protobuf stubs regenerated"

# Test imports
echo ""
echo "🧪 Testing imports..."
cd df && python -c "import score_pb2; import score_pb2_grpc; print('✅ DF stubs work')" && cd ..
cd smft && python -c "import score_pb2; import score_pb2_grpc; print('✅ SMFT stubs work')" && cd ..

echo ""
echo "🎉 Setup complete with protobuf 6.x!"
echo ""
echo "To use this environment:"
echo "  source venv_protobuf6/bin/activate"
echo ""
echo "To run tests:"
echo "  source venv_protobuf6/bin/activate"
echo "  cd df && python 01_steady_server.py &"
echo "  cd smft && N_RPS=10 T_DURATION_SEC=5 python 01_steady_client.py"
echo ""
echo "To deactivate:"
echo "  deactivate"