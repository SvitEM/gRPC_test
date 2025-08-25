#!/usr/bin/env python3
"""
Temporary insecure version of steady client for functional testing
"""
import asyncio
import json
import logging
import os
import sys
import time
from typing import List

import grpc
from dotenv import load_dotenv

# Import generated protobuf stubs
import score_pb2
import score_pb2_grpc


class SteadyLoadGenerator:
    """Generate steady load using insecure channel"""
    
    def __init__(self, host: str, port: int, n_rps: int, duration_sec: int, warmup_sec: int):
        self.host = host
        self.port = port
        self.n_rps = n_rps
        self.duration_sec = duration_sec
        self.warmup_sec = warmup_sec
        self.target = f"{host}:{port}"
        self.results: List[dict] = []
        self.channel = None
        self.stub = None
    
    async def setup_channel(self):
        """Create and configure the reused insecure channel"""
        logging.info(f"Creating insecure channel to {self.target}")
        self.channel = grpc.aio.insecure_channel(self.target)
        self.stub = score_pb2_grpc.ScoreServiceStub(self.channel)
        logging.info("Channel ready for steady load test")
    
    async def close_channel(self):
        """Close the channel"""
        if self.channel:
            await self.channel.close()
            logging.info("Channel closed")
    
    async def send_rpc(self) -> dict:
        """Send single RPC and measure latency"""
        json_data = json.dumps({"vector": list(range(10)), "timestamp": time.time()})
        request = score_pb2.JsonVector(json=json_data)
        
        start_ns = time.perf_counter_ns()
        
        try:
            response = await self.stub.GetScore(request, timeout=10.0)
            end_ns = time.perf_counter_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            return {
                "ok": True,
                "latency_ms": round(latency_ms, 2)
            }
        except grpc.RpcError as e:
            end_ns = time.perf_counter_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            return {
                "ok": False,
                "code": e.code().name,
                "latency_ms": round(latency_ms, 2)
            }
        except Exception as e:
            end_ns = time.perf_counter_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            return {
                "ok": False,
                "error": str(e),
                "latency_ms": round(latency_ms, 2)
            }
    
    async def run_warmup(self):
        """Run warmup phase"""
        if self.warmup_sec <= 0:
            return
            
        logging.info(f"Starting warmup for {self.warmup_sec} seconds at {self.n_rps} RPS")
        
        interval_sec = 1.0 / self.n_rps
        warmup_start = time.perf_counter()
        next_send_time = warmup_start
        
        warmup_results = []
        
        while (time.perf_counter() - warmup_start) < self.warmup_sec:
            current_time = time.perf_counter()
            if current_time < next_send_time:
                await asyncio.sleep(next_send_time - current_time)
            
            result = await self.send_rpc()
            warmup_results.append(result)
            next_send_time += interval_sec
        
        successful = sum(1 for r in warmup_results if r["ok"])
        logging.info(f"Warmup completed: {successful}/{len(warmup_results)} successful RPCs")
    
    async def run_load_test(self):
        """Run the main load test phase"""
        logging.info(f"Starting load test for {self.duration_sec} seconds at {self.n_rps} RPS")
        
        interval_sec = 1.0 / self.n_rps
        test_start = time.perf_counter()
        next_send_time = test_start
        
        while (time.perf_counter() - test_start) < self.duration_sec:
            current_time = time.perf_counter()
            if current_time < next_send_time:
                await asyncio.sleep(next_send_time - current_time)
            
            result = await self.send_rpc()
            self.results.append(result)
            next_send_time += interval_sec
        
        successful = sum(1 for r in self.results if r["ok"])
        total = len(self.results)
        logging.info(f"Load test completed: {successful}/{total} successful RPCs")
    
    def write_results(self, output_file: str):
        """Write results to JSONL file"""
        try:
            with open(output_file, 'w') as f:
                f.write("#TEST=01_steady\n")
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
    n_rps = int(os.getenv('N_RPS', '10'))
    duration_sec = int(os.getenv('T_DURATION_SEC', '10'))
    warmup_sec = int(os.getenv('T_WARMUP_SEC', '2'))
    
    logging.info(f"Insecure Steady Client - Target: {host}:{port}, RPS: {n_rps}, Duration: {duration_sec}s, Warmup: {warmup_sec}s")
    
    generator = SteadyLoadGenerator(host, port, n_rps, duration_sec, warmup_sec)
    
    try:
        await generator.setup_channel()
        await generator.run_warmup()
        await generator.run_load_test()
        generator.write_results("01_steady_results.txt")
        
    except Exception as e:
        logging.error(f"Load test failed: {e}")
        sys.exit(1)
    finally:
        await generator.close_channel()


if __name__ == '__main__':
    asyncio.run(main())