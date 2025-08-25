#!/usr/bin/env python3
"""
Temporary insecure version of cold connection client for functional testing
"""
import asyncio
import json
import logging
import os
import sys
import time
from typing import List

import grpc

# Import generated protobuf stubs
import score_pb2
import score_pb2_grpc


class ColdConnectionGenerator:
    """Generate cold connection tests with insecure channels"""
    
    def __init__(self, host: str, port: int, duration_sec: int):
        self.host = host
        self.port = port
        self.duration_sec = duration_sec
        self.target = f"{host}:{port}"
        self.results: List[dict] = []
    
    async def create_channel(self) -> grpc.aio.Channel:
        """Create new insecure channel for single attempt"""
        return grpc.aio.insecure_channel(self.target)
    
    async def cold_connection_attempt(self) -> dict:
        """Perform single cold connection attempt with timing measurements"""
        
        channel = None
        try:
            # Start total timing
            total_start_ns = time.perf_counter_ns()
            
            # Create channel (no connection time measurement for insecure)
            channel = await self.create_channel()
            connect_end_ns = time.perf_counter_ns()
            t_connect_ms = (connect_end_ns - total_start_ns) / 1_000_000.0
            
            # Create stub and prepare request
            stub = score_pb2_grpc.ScoreServiceStub(channel)
            json_data = json.dumps({"vector": list(range(5)), "timestamp": time.time()})
            request = score_pb2.JsonVector(json=json_data)
            
            # Measure first RPC time
            rpc_start_ns = time.perf_counter_ns()
            await stub.GetScore(request, timeout=10.0)
            rpc_end_ns = time.perf_counter_ns()
            t_first_rpc_ms = (rpc_end_ns - rpc_start_ns) / 1_000_000.0
            
            total_end_ns = time.perf_counter_ns()
            t_total_ms = (total_end_ns - total_start_ns) / 1_000_000.0
            
            return {
                "ok": True,
                "t_connect_ms": round(t_connect_ms, 1),
                "t_first_rpc_ms": round(t_first_rpc_ms, 1), 
                "t_total_ms": round(t_total_ms, 1)
            }
            
        except grpc.RpcError as e:
            total_end_ns = time.perf_counter_ns()
            t_total_ms = (total_end_ns - total_start_ns) / 1_000_000.0
            
            return {
                "ok": False,
                "code": e.code().name,
                "t_connect_ms": 0.0,
                "t_first_rpc_ms": 0.0,
                "t_total_ms": round(t_total_ms, 1)
            }
        except Exception as e:
            total_end_ns = time.perf_counter_ns()
            t_total_ms = (total_end_ns - total_start_ns) / 1_000_000.0
            
            return {
                "ok": False,
                "error": str(e),
                "t_connect_ms": 0.0,
                "t_first_rpc_ms": 0.0,
                "t_total_ms": round(t_total_ms, 1)
            }
        finally:
            if channel:
                await channel.close()
    
    async def run_cold_connection_test(self):
        """Run cold connection test at 1 RPS"""
        logging.info(f"Starting cold connection test for {self.duration_sec} seconds at 1 RPS")
        
        test_start = time.perf_counter()
        attempt_count = 0
        
        while (time.perf_counter() - test_start) < self.duration_sec:
            attempt_start = time.perf_counter()
            
            # Perform cold connection attempt
            result = await self.cold_connection_attempt()
            self.results.append(result)
            attempt_count += 1
            
            logging.info(f"Attempt {attempt_count}: {result}")
            
            # Wait for next attempt (1 RPS = 1 second interval)
            attempt_duration = time.perf_counter() - attempt_start
            sleep_time = max(0, 1.0 - attempt_duration)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        successful = sum(1 for r in self.results if r["ok"])
        total = len(self.results)
        logging.info(f"Cold connection test completed: {successful}/{total} successful attempts")
    
    def write_results(self, output_file: str):
        """Write results to JSONL file"""
        try:
            with open(output_file, 'w') as f:
                f.write("#TEST=02_coldconn\n")
                for result in self.results:
                    f.write(json.dumps(result) + "\n")
                
            logging.info(f"Results written to {output_file}")
        except Exception as e:
            logging.error(f"Error writing results: {e}")
            raise


async def main():
    """Main entry point"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    host = "localhost"
    port = 50052  # Use insecure port
    duration_sec = int(os.getenv('T_DURATION_SEC', '5'))
    
    logging.info(f"Insecure Cold Connection Client - Target: {host}:{port}, Duration: {duration_sec}s")
    
    generator = ColdConnectionGenerator(host, port, duration_sec)
    
    try:
        await generator.run_cold_connection_test()
        generator.write_results("02_coldconn_results.txt")
        
    except Exception as e:
        logging.error(f"Cold connection test failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())