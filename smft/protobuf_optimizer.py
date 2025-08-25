#!/usr/bin/env python3
"""
Robust Protobuf Implementation Optimizer
Tries UPB → CPP → Python in order and reports which is active
"""
import os
import warnings
import logging

def optimize_protobuf():
    """
    Try protobuf implementations in order of performance: UPB → CPP → Python
    Returns the implementation that's actually working
    """
    
    # Suppress protobuf warnings during detection
    warnings.filterwarnings('ignore', category=UserWarning, module='google.protobuf')
    
    # Implementation preference order (fastest to slowest)
    implementations = [
        ('upb', 'UPB (Ultra-fast Parser)'),
        ('cpp', 'C++ (Fast compiled implementation)'), 
        ('python', 'Python (Pure Python fallback)')
    ]
    
    working_impl = None
    actual_impl = None
    
    for impl_name, impl_desc in implementations:
        try:
            # Set the environment variable
            os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = impl_name
            
            # Clear any cached imports to force re-detection
            modules_to_clear = [
                'google.protobuf.internal.api_implementation',
                'google.protobuf.pyext._message',
                'google.protobuf.message'
            ]
            
            for module in modules_to_clear:
                if module in globals():
                    del globals()[module]
            
            # Test import to see if it works
            import google.protobuf
            from google.protobuf.internal import api_implementation
            
            # Check what we actually got
            actual_impl = api_implementation.Type()
            
            # Verify it actually works by creating a simple message
            from google.protobuf import descriptor_pb2
            test_msg = descriptor_pb2.FileDescriptorProto()
            test_msg.name = "test"
            _ = test_msg.SerializeToString()  # This will fail if backend is broken
            
            working_impl = impl_name
            break
            
        except Exception as e:
            # Log the failure for debugging
            print(f"   {impl_name}: ❌ Failed ({type(e).__name__})")
            continue
    
    # Clean up environment if everything failed
    if not working_impl:
        if 'PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION' in os.environ:
            del os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION']
        working_impl = 'default'
        actual_impl = 'unknown'
    
    return working_impl, actual_impl


def get_protobuf_info():
    """Get detailed protobuf information for logging"""
    try:
        import google.protobuf
        from google.protobuf.internal import api_implementation
        
        version = google.protobuf.__version__
        implementation = api_implementation.Type()
        
        # Performance rating
        perf_rating = {
            'upb': '⚡ Ultra-Fast',
            'cpp': '🚀 Fast', 
            'python': '🐌 Slow'
        }.get(implementation, '❓ Unknown')
        
        return {
            'version': version,
            'implementation': implementation,
            'performance': perf_rating
        }
    except Exception as e:
        return {
            'version': 'unknown',
            'implementation': 'unknown',
            'performance': f'❌ Error: {e}',
            'error': str(e)
        }


def log_protobuf_status(logger=None):
    """Log protobuf status in a nice format"""
    if logger is None:
        # Create a simple logger if none provided
        logger = logging.getLogger(__name__)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(levelname)s: %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
    
    info = get_protobuf_info()
    
    logger.info("=" * 50)
    logger.info("🔬 PROTOBUF CONFIGURATION")
    logger.info(f"   Version: {info['version']}")
    logger.info(f"   Implementation: {info['implementation'].upper()}")
    logger.info(f"   Performance: {info['performance']}")
    
    if info['implementation'] in ['upb', 'cpp']:
        logger.info("   ✅ Using optimized implementation - excellent performance!")
    elif info['implementation'] == 'python':
        logger.warning("   ⚠️  Using pure Python - performance may be 3-5x slower")
    else:
        logger.warning(f"   ❓ Unknown implementation - check for issues")
    
    logger.info("=" * 50)


if __name__ == '__main__':
    print("🔍 Testing Protobuf Implementations...")
    print()
    
    working, actual = optimize_protobuf()
    
    print(f"🎯 Selected Implementation: {working}")
    print(f"🔍 Actual Implementation: {actual}")
    print()
    
    log_protobuf_status()