#!/usr/bin/env python3
"""
Test script to verify protobuf optimization is working
"""
import time
from protobuf_optimizer import optimize_protobuf, log_protobuf_status

def test_protobuf_performance():
    """Test protobuf serialization performance"""
    print("🚀 Testing Protobuf Performance...")
    print()
    
    # Optimize protobuf
    working_impl, actual_impl = optimize_protobuf()
    print(f"Selected: {working_impl}, Actual: {actual_impl}")
    print()
    
    # Log status
    log_protobuf_status()
    
    # Performance test
    try:
        import score_pb2
        
        # Create test message
        response = score_pb2.ScoreResponse()
        response.score = 0.12345
        
        # Serialize/deserialize test
        iterations = 10000
        print(f"🧪 Performance test ({iterations:,} iterations)...")
        
        start_time = time.perf_counter()
        
        for _ in range(iterations):
            # Serialize
            data = response.SerializeToString()
            
            # Deserialize
            new_response = score_pb2.ScoreResponse()
            new_response.ParseFromString(data)
        
        elapsed_time = time.perf_counter() - start_time
        ops_per_sec = iterations / elapsed_time
        us_per_op = (elapsed_time * 1_000_000) / iterations
        
        print(f"   ⏱️  Total time: {elapsed_time:.3f}s")
        print(f"   📊 Operations/sec: {ops_per_sec:,.0f}")
        print(f"   ⚡ Microseconds/operation: {us_per_op:.2f}μs")
        
        if actual_impl in ['cpp', 'upb']:
            if us_per_op < 10:
                print("   ✅ Excellent performance - optimized implementation working!")
            else:
                print("   ⚠️  Performance seems slow for optimized implementation")
        else:
            print("   ⚠️  Using Python implementation - expect 3-5x slower performance")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Performance test failed: {e}")
        return False

if __name__ == '__main__':
    success = test_protobuf_performance()
    exit(0 if success else 1)