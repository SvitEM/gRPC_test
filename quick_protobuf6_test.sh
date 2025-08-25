#!/bin/bash
# Quick test of protobuf 6.x setup
set -e

echo "🧪 Quick test of protobuf 6.x..."

# Create virtual environment in current directory
echo "📦 Creating virtual environment..."
python3.11 -m venv venv_test
source venv_test/bin/activate

# Install latest optimized versions
echo "📦 Installing latest optimized protobuf + gRPC..."
pip install -q -r requirements-protobuf6.txt

# Check versions and implementation
echo "📊 Installed versions:"
python -c "import google.protobuf; print(f'protobuf: {google.protobuf.__version__}')"
echo "🔍 Testing protobuf implementations..."
python protobuf_optimizer.py

# Regenerate stubs
echo "🔨 Regenerating stubs..."
python -m grpc_tools.protoc --proto_path=proto --python_out=df --grpc_python_out=df proto/score.proto
python -m grpc_tools.protoc --proto_path=proto --python_out=smft --grpc_python_out=smft proto/score.proto

# Test imports
echo "🧪 Testing imports..."
cd df && python -c "import score_pb2; print('✅ DF protobuf 6.x works')" && cd ..
cd smft && python -c "import score_pb2; print('✅ SMFT protobuf 6.x works')" && cd ..

# Test server start
echo "🚀 Testing server start..."
python df/01_steady_server.py &
SERVER_PID=$!
sleep 2

if kill -0 $SERVER_PID 2>/dev/null; then
    echo "✅ Server running with protobuf 6.x!"
    kill $SERVER_PID
else
    echo "❌ Server failed to start"
fi

deactivate
echo "🎉 Protobuf 6.x test complete!"