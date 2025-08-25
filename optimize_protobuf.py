#!/usr/bin/env python3
"""
Protobuf C++ Implementation Optimization Script
Ensures protobuf is using the fastest C++ implementation
"""
import os
import sys

def optimize_protobuf():
    """Force protobuf to use C++ implementation for maximum performance"""
    
    # Force C++ implementation (fastest)
    os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'cpp'
    
    # Disable pure Python fallback
    os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION_VERSION'] = '2'
    
    # Import protobuf and verify C++ implementation
    try:
        import google.protobuf
        from google.protobuf.internal import api_implementation
        
        impl = api_implementation.Type()
        print(f"Protobuf implementation: {impl}")
        print(f"Protobuf version: {google.protobuf.__version__}")
        
        if impl == 'cpp':
            print("✅ Using fast C++ protobuf implementation")
            return True
        elif impl == 'upb':
            print("⚡ Using ultra-fast UPB protobuf implementation") 
            return True
        else:
            print("⚠️  Using slow Python protobuf implementation")
            print("   Consider rebuilding protobuf with C++ extensions")
            return False
            
    except ImportError as e:
        print(f"❌ Failed to import protobuf: {e}")
        return False

if __name__ == '__main__':
    optimize_protobuf()