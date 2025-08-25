#!/usr/bin/env python3
"""
SMFT Steady Client - Load generator with fixed RPS and reused channel
"""
import asyncio
import gc
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

# Optimize protobuf implementation for best performance
import sys
sys.path.insert(0, '..')
from protobuf_optimizer import optimize_protobuf
optimize_protobuf()

import grpc
from dotenv import load_dotenv

# Import generated protobuf stubs
import score_pb2
import score_pb2_grpc

# High-performance event loop
try:
    import uvloop
except ImportError:
    uvloop = None


class HighResTimer:
    """High-resolution timer with reduced system call overhead"""
    def __init__(self):
        self._offset = time.perf_counter_ns()
    
    def now_ns(self):
        return time.perf_counter_ns() - self._offset


class SteadyLoadGenerator:
    """Generate steady load using one reused channel"""
    
    def __init__(self, host: str, port: int, n_rps: int, duration_sec: int, warmup_sec: int,
                 ca_cert: bytes, client_cert: bytes, client_key: bytes, df_delay_ms: float = 0.0):
        self.host = host
        self.port = port
        self.n_rps = n_rps
        self.duration_sec = duration_sec
        self.warmup_sec = warmup_sec
        self.df_delay_ms = df_delay_ms
        self.target = f"{host}:{port}"
        
        # Create SSL credentials (server-side TLS only for now)
        self.credentials = grpc.ssl_channel_credentials(
            root_certificates=ca_cert,
            private_key=None,
            certificate_chain=None
        )
        
        # gRPC channel options for performance
        self.channel_options = [
            ('grpc.so_reuseport', 1),              # Enable SO_REUSEPORT for client
            ('grpc.keepalive_time_ms', 3600000),  # 1 hour keepalive
            ('grpc.keepalive_timeout_ms', 5000),   # 5 second timeout
            ('grpc.keepalive_permit_without_calls', True),  # Allow keepalive without calls
            ('grpc.http2.max_pings_without_data', 0),  # No limit on pings
            ('grpc.http2.min_ping_interval_without_data_ms', 60000),  # 1 minute between pings
            ('grpc.http2.min_time_between_pings_ms', 60000),  # 1 minute between pings
            ('grpc.max_send_message_length', 1024),    # Small message limit
            ('grpc.max_receive_message_length', 1024), # Small response limit
            ('grpc.max_concurrent_streams', 1024),
        ]
        
        self.results: List[dict] = []
        self.channel = None
        self.stub = None
        
        # Pre-allocate request object to avoid repeated allocation
        self.request = score_pb2.JsonVector(json="{}")
        
        # Memory pre-allocation pool for result objects
        self.result_pool = [
            {"ok": True, "latency_ms": 0.0, "net_latency_ms": 0.0} 
            for _ in range(1000)
        ]
        self.pool_index = 0
        
        # High-resolution timer for reduced system call overhead
        self.timer = HighResTimer()
        
        # Batch results writing to reduce I/O overhead
        self.result_buffer = []
        self.batch_size = 1000
    
    async def setup_channel(self):
        """Create and configure the reused secure channel"""
        logging.info(f"Creating secure channel to {self.target}")
        self.channel = grpc.aio.secure_channel(self.target, self.credentials, options=self.channel_options)
        self.stub = score_pb2_grpc.ScoreServiceStub(self.channel)
        
        # Wait for channel to be ready
        try:
            await asyncio.wait_for(self.channel.channel_ready(), timeout=30.0)
            logging.info("Channel ready for steady load test")
        except asyncio.TimeoutError:
            logging.error("Channel failed to become ready within 30 seconds")
            raise
    
    async def close_channel(self):
        """Close the secure channel"""
        if self.channel:
            await self.channel.close()
            logging.info("Channel closed")
    
    async def send_rpc(self) -> dict:
        """Send single RPC and measure latency"""
        start_ns = self.timer.now_ns()
        
        try:
            _ = await self.stub.GetScore(
                self.request, 
                timeout=0.05,  # 50ms timeout
                compression=grpc.Compression.NoCompression
            )
            end_ns = self.timer.now_ns()
            total_latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            # Subtract DF server artificial delay to get network/processing overhead
            net_latency_ms = total_latency_ms - self.df_delay_ms
            
            # Reuse pre-allocated result object to reduce GC pressure
            result = self.result_pool[self.pool_index]
            result["ok"] = True
            result["latency_ms"] = round(total_latency_ms, 2)
            result["net_latency_ms"] = round(net_latency_ms, 2)
            self.pool_index = (self.pool_index + 1) % 1000
            return result
        except grpc.RpcError as e:
            end_ns = self.timer.now_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            # Reuse pre-allocated result object for errors too
            result = self.result_pool[self.pool_index]
            result["ok"] = False
            result["code"] = e.code().name
            result["latency_ms"] = round(latency_ms, 2)
            # Remove net_latency_ms for error cases
            result.pop("net_latency_ms", None)
            self.pool_index = (self.pool_index + 1) % 1000
            return result
        except Exception as e:
            end_ns = self.timer.now_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            # Reuse pre-allocated result object for general errors
            result = self.result_pool[self.pool_index]
            result["ok"] = False
            result["error"] = str(e)
            result["latency_ms"] = round(latency_ms, 2)
            # Remove net_latency_ms for error cases
            result.pop("net_latency_ms", None)
            self.pool_index = (self.pool_index + 1) % 1000
            return result
    
    async def run_warmup(self):
        """Run warmup phase with concurrent execution"""
        if self.warmup_sec <= 0:
            return
            
        logging.info(f"Starting warmup for {self.warmup_sec} seconds at {self.n_rps} RPS")
        
        # Calculate interval between request starts
        interval_sec = 1.0 / self.n_rps
        warmup_start = time.perf_counter()
        next_send_time = warmup_start
        
        warmup_results = []
        active_tasks = []
        max_concurrent = min(self.n_rps * 2, 500)  # Lower limit for warmup
        
        while (time.perf_counter() - warmup_start) < self.warmup_sec:
            current_time = time.perf_counter()
            
            # Clean up completed tasks
            completed_tasks = [task for task in active_tasks if task.done()]
            for task in completed_tasks:
                try:
                    result = await task
                    warmup_results.append(result)
                except Exception as e:
                    logging.error(f"Warmup task failed: {e}")
            
            # Remove completed tasks
            active_tasks = [task for task in active_tasks if not task.done()]
            
            # Send new request if it's time and we're not at concurrency limit
            if current_time >= next_send_time and len(active_tasks) < max_concurrent:
                task = asyncio.create_task(self.send_rpc())
                active_tasks.append(task)
                next_send_time += interval_sec
            else:
                await asyncio.sleep(0.001)  # Small sleep to avoid busy waiting
        
        # Wait for remaining warmup tasks
        if active_tasks:
            remaining_results = await asyncio.gather(*active_tasks, return_exceptions=True)
            for result in remaining_results:
                if not isinstance(result, Exception):
                    warmup_results.append(result)
        
        successful = sum(1 for r in warmup_results if r["ok"])
        logging.info(f"Warmup completed: {successful}/{len(warmup_results)} successful RPCs")
    
    async def run_load_test(self):
        """Run the main load test phase with concurrent RPC execution"""
        logging.info(f"Starting load test for {self.duration_sec} seconds at {self.n_rps} RPS")
        
        # Calculate interval between request starts
        interval_sec = 1.0 / self.n_rps
        test_start = time.perf_counter()
        next_send_time = test_start
        
        # Track active tasks to manage concurrency
        active_tasks = []
        max_concurrent = min(self.n_rps * 2, 1000)  # Allow 2x RPS concurrent requests, max 1000
        
        while (time.perf_counter() - test_start) < self.duration_sec:
            current_time = time.perf_counter()
            
            # Clean up completed tasks and collect results
            completed_tasks = [task for task in active_tasks if task.done()]
            for task in completed_tasks:
                try:
                    result = await task
                    self.result_buffer.append(result.copy())
                except Exception as e:
                    logging.error(f"Task failed: {e}")
                    # Add error result
                    error_result = self.result_pool[self.pool_index]
                    error_result["ok"] = False
                    error_result["code"] = "TASK_ERROR"
                    self.result_buffer.append(error_result.copy())
                    self.pool_index = (self.pool_index + 1) % 1000
            
            # Remove completed tasks
            active_tasks = [task for task in active_tasks if not task.done()]
            
            # Flush buffer periodically
            if len(self.result_buffer) >= self.batch_size:
                self.results.extend(self.result_buffer)
                self.result_buffer.clear()
            
            # Send new request if it's time and we're not at concurrency limit
            if current_time >= next_send_time and len(active_tasks) < max_concurrent:
                # Create new task for RPC
                task = asyncio.create_task(self.send_rpc())
                active_tasks.append(task)
                
                # Schedule next request
                next_send_time += interval_sec
            else:
                # Small sleep to avoid busy waiting
                await asyncio.sleep(0.001)  # 1ms
        
        # Wait for all remaining tasks to complete
        if active_tasks:
            logging.info(f"Waiting for {len(active_tasks)} remaining tasks to complete...")
            remaining_results = await asyncio.gather(*active_tasks, return_exceptions=True)
            
            for result in remaining_results:
                if isinstance(result, Exception):
                    logging.error(f"Final task failed: {result}")
                    error_result = self.result_pool[self.pool_index]
                    error_result["ok"] = False
                    error_result["code"] = "TASK_ERROR"
                    self.result_buffer.append(error_result.copy())
                    self.pool_index = (self.pool_index + 1) % 1000
                else:
                    self.result_buffer.append(result.copy())
        
        # Flush remaining results
        if self.result_buffer:
            self.results.extend(self.result_buffer)
            self.result_buffer.clear()
        
        successful = sum(1 for r in self.results if r["ok"])
        total = len(self.results)
        actual_rps = total / self.duration_sec if self.duration_sec > 0 else 0
        logging.info(f"Load test completed: {successful}/{total} successful RPCs (actual RPS: {actual_rps:.1f})")
    
    def write_results(self, output_file: str):
        """Write results to JSONL file"""
        try:
            with open(output_file, 'w') as f:
                # Write header
                f.write("#TEST=01_steady\n")
                
                # Write results
                for result in self.results:
                    f.write(json.dumps(result) + "\n")
                
            logging.info(f"Results written to {output_file}")
        except Exception as e:
            logging.error(f"Error writing results: {e}")
            raise


async def main():
    """Main entry point"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Log detailed protobuf status
    try:
        from protobuf_optimizer import log_protobuf_status
        log_protobuf_status(logging.getLogger())
    except ImportError:
        logging.warning("Could not import protobuf optimizer")
    
    # Load environment configuration
    load_dotenv()
    
    host = os.getenv('DF_HOST', 'localhost')
    port = int(os.getenv('DF_PORT', '50051'))
    n_rps = int(os.getenv('N_RPS', '500'))
    duration_sec = int(os.getenv('T_DURATION_SEC', '300'))
    warmup_sec = int(os.getenv('T_WARMUP_SEC', '30'))
    df_delay_ms = float(os.getenv('DF_DELAY_MS', '5.0'))
    tls_ca = os.getenv('TLS_CA', 'certs/ca.crt')
    tls_cert = os.getenv('TLS_CERT', 'certs/client.crt')
    tls_key = os.getenv('TLS_KEY', 'certs/client.key')
    
    logging.info(f"SMFT Steady Client starting - Target: {host}:{port}, RPS: {n_rps}, Duration: {duration_sec}s, Warmup: {warmup_sec}s, DF Delay: {df_delay_ms}ms")
    
    # Validate certificate files
    cert_files = [tls_ca, tls_cert, tls_key]
    for cert_file in cert_files:
        if not Path(cert_file).exists():
            logging.error(f"Certificate file not found: {cert_file}")
            sys.exit(1)
    
    # Read certificate files
    try:
        with open(tls_ca, 'rb') as f:
            ca_cert = f.read()
        with open(tls_cert, 'rb') as f:
            client_cert = f.read()
        with open(tls_key, 'rb') as f:
            client_key = f.read()
    except Exception as e:
        logging.error(f"Error reading certificate files: {e}")
        sys.exit(1)
    
    # Create and run load generator
    generator = SteadyLoadGenerator(
        host, port, n_rps, duration_sec, warmup_sec,
        ca_cert, client_cert, client_key, df_delay_ms
    )
    
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
    # Install uvloop for better performance if available
    if uvloop:
        uvloop.install()
        logging.info("Using uvloop for high-performance event loop")
    
    # Optimize garbage collection for stability
    gc.set_threshold(700, 10, 10)  # More aggressive GC to reduce pauses
    
    # CPU affinity for reduced context switching (Linux only)
    try:
        os.sched_setaffinity(0, {0, 1})  # Pin to cores 0,1
        logging.info("Pinned client to CPU cores 0,1")
    except (AttributeError, OSError):
        pass  # Not available on macOS or permission denied
    
    asyncio.run(main())