#!/usr/bin/env python3
"""
SMFT Cold Connection Client - New channel per request to measure connection overhead
"""
import asyncio
import gc
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import List

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


class ColdConnectionGenerator:
    """Generate cold connection tests with new channel per attempt"""
    
    def __init__(self, host: str, port: int, duration_sec: int,
                 ca_cert: bytes, client_cert: bytes, client_key: bytes, df_delay_ms: float = 0.0):
        self.host = host
        self.port = port
        self.duration_sec = duration_sec
        self.df_delay_ms = df_delay_ms
        self.target = f"{host}:{port}"
        self.ca_cert = ca_cert
        self.client_cert = client_cert
        self.client_key = client_key
        
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
        ]
        
        self.results: List[dict] = []
        
        # Pre-allocate request object to avoid repeated allocation  
        self.request = score_pb2.JsonVector(json="{}")
        
        # High-resolution timer for reduced system call overhead
        self.timer = HighResTimer()
    
    async def create_channel(self) -> grpc.aio.Channel:
        """Create new secure channel for single attempt"""
        credentials = grpc.ssl_channel_credentials(
            root_certificates=self.ca_cert,
            private_key=None,
            certificate_chain=None
        )
        
        return grpc.aio.secure_channel(self.target, credentials, options=self.channel_options)
    
    async def cold_connection_attempt(self) -> dict:
        """Perform single cold connection attempt with timing measurements"""
        
        channel = None
        try:
            # Start total timing
            total_start_ns = self.timer.now_ns()
            
            # Create channel
            channel = await self.create_channel()
            
            # Measure connection time (TCP + TLS + HTTP/2 handshake)
            connect_start_ns = self.timer.now_ns()
            await asyncio.wait_for(channel.channel_ready(), timeout=30.0)
            connect_end_ns = self.timer.now_ns()
            t_connect_ms = (connect_end_ns - connect_start_ns) / 1_000_000.0
            
            # Create stub and measure first RPC time
            stub = score_pb2_grpc.ScoreServiceStub(channel)
            
            # Measure first RPC time
            rpc_start_ns = self.timer.now_ns()
            await stub.GetScore(
                self.request, 
                timeout=0.05,  # 50ms timeout
                wait_for_ready=True,
                compression=grpc.Compression.NoCompression
            )
            rpc_end_ns = self.timer.now_ns()
            t_first_rpc_ms = (rpc_end_ns - rpc_start_ns) / 1_000_000.0
            
            total_end_ns = self.timer.now_ns()
            t_total_ms = (total_end_ns - total_start_ns) / 1_000_000.0
            
            # Subtract DF server artificial delay from RPC time
            net_rpc_ms = t_first_rpc_ms - self.df_delay_ms
            net_total_ms = t_total_ms - self.df_delay_ms
            
            return {
                "ok": True,
                "t_connect_ms": round(t_connect_ms, 1),
                "t_first_rpc_ms": round(t_first_rpc_ms, 1),
                "t_total_ms": round(t_total_ms, 1),
                "net_rpc_ms": round(net_rpc_ms, 1),
                "net_total_ms": round(net_total_ms, 1)
            }
            
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "error": "connection_timeout",
                "t_connect_ms": 30000.0,  # timeout value
                "t_first_rpc_ms": 0.0,
                "t_total_ms": 30000.0
            }
        except grpc.RpcError as e:
            total_end_ns = time.perf_counter_ns()
            t_total_ms = (total_end_ns - total_start_ns) / 1_000_000.0
            
            return {
                "ok": False,
                "code": e.code().name,
                "t_connect_ms": 0.0,  # connection succeeded if we got RPC error
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
            
            # Log progress periodically
            if attempt_count % 10 == 0:
                successful = sum(1 for r in self.results if r["ok"])
                logging.info(f"Completed {attempt_count} attempts, {successful} successful")
            
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
                # Write header
                f.write("#TEST=02_coldconn\n")
                
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
    duration_sec = int(os.getenv('T_DURATION_SEC', '300'))
    df_delay_ms = float(os.getenv('DF_DELAY_MS', '5.0'))
    tls_ca = os.getenv('TLS_CA', 'certs/ca.crt')
    tls_cert = os.getenv('TLS_CERT', 'certs/client.crt')
    tls_key = os.getenv('TLS_KEY', 'certs/client.key')
    
    logging.info(f"SMFT Cold Connection Client starting - Target: {host}:{port}, Duration: {duration_sec}s, DF Delay: {df_delay_ms}ms")
    
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
    
    # Create and run cold connection generator
    generator = ColdConnectionGenerator(
        host, port, duration_sec,
        ca_cert, client_cert, client_key, df_delay_ms
    )
    
    try:
        await generator.run_cold_connection_test()
        generator.write_results("02_coldconn_results.txt")
        
    except Exception as e:
        logging.error(f"Cold connection test failed: {e}")
        sys.exit(1)


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