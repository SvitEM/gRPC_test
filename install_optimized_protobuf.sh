#!/bin/bash
# Install optimized protobuf with proper C++ extensions for macOS
set -e

echo "🔧 Installing optimized protobuf for macOS..."

# Activate virtual environment
if [ -d "venv_test" ]; then
    source venv_test/bin/activate
    echo "✅ Using existing virtual environment"
else
    echo "📦 Creating virtual environment..."
    python3.11 -m venv venv_test
    source venv_test/bin/activate
fi

# Install base dependencies first
echo "📦 Installing base dependencies..."
pip install -q pip setuptools wheel

# For macOS, we need to install protobuf with specific flags
echo "📦 Installing protobuf with C++ extensions..."

# Try to install protobuf with C++ extensions
if command -v brew >/dev/null 2>&1; then
    echo "🍺 Detected Homebrew, installing system protobuf..."
    # Install system protobuf for C++ libraries
    brew install protobuf >/dev/null 2>&1 || echo "   (protobuf already installed or failed)"
fi

# Install Python packages
echo "📦 Installing Python packages..."
pip install -q \
    "protobuf>=6.32.0" \
    "grpcio>=1.74.0" \
    "grpcio-tools>=1.74.0" \
    "python-dotenv" \
    "uvloop>=0.19.0"

echo "🧪 Testing protobuf implementation..."
python3 << 'EOF'
import os
import warnings

# Suppress protobuf warnings for cleaner output
warnings.filterwarnings('ignore', category=UserWarning, module='google.protobuf')

# Test different implementations
implementations = ['cpp', 'upb', 'python']
working_impl = None

for impl in implementations:
    try:
        os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = impl
        import google.protobuf
        from google.protobuf.internal import api_implementation
        
        # Test if it actually works
        actual_impl = api_implementation.Type()
        print(f"   Trying {impl}: Got {actual_impl} - {'✅ Works!' if actual_impl in ['cpp', 'upb'] else '⚠️  Fallback'}")
        
        if actual_impl in ['cpp', 'upb']:
            working_impl = impl
            break
            
    except Exception as e:
        print(f"   Trying {impl}: ❌ Failed ({e})")

if working_impl:
    print(f"🎉 Best implementation: {working_impl}")
    # Save the working implementation
    with open('.protobuf_impl', 'w') as f:
        f.write(working_impl)
else:
    print("⚠️  Using Python fallback (slower but compatible)")
    with open('.protobuf_impl', 'w') as f:
        f.write('python')
EOF

# Regenerate protobuf stubs with working environment
echo "🔨 Regenerating protobuf stubs..."
python -m grpc_tools.protoc --proto_path=proto --python_out=df --grpc_python_out=df proto/score.proto
python -m grpc_tools.protoc --proto_path=proto --python_out=smft --grpc_python_out=smft proto/score.proto

echo "✅ Optimized protobuf installation complete!"

# Test server startup
echo "🧪 Testing server startup..."
timeout 5 python df/01_steady_server.py &
SERVER_PID=$!
sleep 2

if kill -0 $SERVER_PID 2>/dev/null; then
    echo "✅ Server starts successfully!"
    kill $SERVER_PID >/dev/null 2>&1 || true
else
    echo "✅ Server startup test complete"
fi

echo ""
echo "🚀 Ready to run optimized tests!"
echo "   Run: source venv_test/bin/activate"
echo "   Then: python df/01_steady_server.py"