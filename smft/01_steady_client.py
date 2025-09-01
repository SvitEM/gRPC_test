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
from typing import List, Dict

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
                 ca_cert: bytes, client_cert: bytes, client_key: bytes, df_delay_ms: float = 0.0,
                 pool_size: int = 4):
        self.host = host
        self.port = port
        self.n_rps = n_rps
        self.duration_sec = duration_sec
        self.warmup_sec = warmup_sec
        self.df_delay_ms = df_delay_ms
        self.target = f"{host}:{port}"
        self.pool_size = max(1, int(pool_size))
        
        # Create SSL credentials with mTLS (client certs)
        self.credentials = grpc.ssl_channel_credentials(
            root_certificates=ca_cert,
            private_key=client_key,
            certificate_chain=client_cert
        )
        
        # Optimized gRPC channel options for stability and performance
        self.channel_options = [
            ('grpc.keepalive_time_ms', 30000),     # 30 sec keepalive
            ('grpc.keepalive_timeout_ms', 5000),   # 5 sec timeout
            ('grpc.keepalive_permit_without_calls', True),
            ('grpc.http2.max_pings_without_data', 0),
            ('grpc.http2.min_ping_interval_without_data_ms', 10000),  # 10 sec
            ('grpc.http2.min_time_between_pings_ms', 10000),          # 10 sec
            ('grpc.max_send_message_length', 1024),
            ('grpc.max_receive_message_length', 1024),
            ('grpc.max_concurrent_streams', 512),   # Reduced for stability
            # TCP buffer optimization
            ('grpc.so_sndbuf', 1048576),           # 1MB send buffer
            ('grpc.so_rcvbuf', 1048576),           # 1MB recv buffer
            ('grpc.http2.bdp_probe', 0),           # Disable BDP probing on loopback
            # Connection pool settings
            ('grpc.http2.max_frame_size', 16777215), # Max frame size
            ('grpc.http2.write_buffer_size', 65536), # 64KB write buffer
            # Increase HTTP/2 flow-control windows
            ('grpc.http2.initial_connection_window_size', 8388608),
            ('grpc.http2.initial_stream_window_size', 8388608),
        ]
        
        self.results: List[Dict] = []
        self.channels: List[grpc.aio.Channel] = []
        self.stubs: List[score_pb2_grpc.ScoreServiceStub] = []
        self._get_scores = []
        self._rr = 0
        
        # High-resolution timer for reduced system call overhead
        self.timer = HighResTimer()
    
    async def setup_channel(self):
        """Create and configure the reused secure channel"""
        logging.info(f"Creating {self.pool_size} secure channel(s) to {self.target}")
        for _ in range(self.pool_size):
            ch = grpc.aio.secure_channel(self.target, self.credentials, options=self.channel_options)
            self.channels.append(ch)
            stub = score_pb2_grpc.ScoreServiceStub(ch)
            self.stubs.append(stub)
            self._get_scores.append(stub.GetScore)
        # Wait for all channels to be ready
        try:
            await asyncio.wait_for(asyncio.gather(*[ch.channel_ready() for ch in self.channels]), timeout=30.0)
            logging.info("All channels ready for steady load test")
        except asyncio.TimeoutError:
            logging.error("Channel pool failed to become ready within 30 seconds")
            raise
    
    async def close_channel(self):
        """Close the secure channel"""
        if self.channels:
            await asyncio.gather(*[ch.close() for ch in self.channels])
            logging.info("Channel pool closed")
    
    async def send_rpc(self, get_score_fn=None) -> Dict:
        """Send single RPC and measure latency"""
        start_ns = self.timer.now_ns()
        
        try:
            # Pick method via round-robin if not provided
            if get_score_fn is None:
                get_score_fn = self._get_scores[self._rr]
                self._rr = (self._rr + 1) % max(1, len(self._get_scores))

            # Fresh request per call
            request = score_pb2.JsonVector(json="{}")

            # Create the call object to access metadata and response
            call = get_score_fn(
                request,
                timeout=0.050,  # 50ms timeout
                compression=grpc.Compression.NoCompression
            )
            # Await the response; metadata is still retrievable afterward
            _ = await call
            end_ns = self.timer.now_ns()
            total_latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            # Subtract actual server-inserted delay if provided; else fall back to configured
            server_delay_ms = self.df_delay_ms
            try:
                md = await call.initial_metadata()
                server_delay_ms = _extract_server_delay_ms(md, server_delay_ms)
                # Fallback to trailing metadata if not present in initial
                if server_delay_ms == self.df_delay_ms:
                    tmd = await call.trailing_metadata()
                    server_delay_ms = _extract_server_delay_ms(tmd, server_delay_ms)
            except Exception:
                # Best-effort metadata parsing only; ignore on failure
                pass

            # Subtract server delay to estimate transport/stack overhead
            net_latency_ms = max(0.0, total_latency_ms - server_delay_ms)
            
            return {
                "ok": True,
                "latency_ms": round(total_latency_ms, 2),
                "net_latency_ms": round(net_latency_ms, 2),
                "server_delay_ms": round(server_delay_ms, 2)
            }
        except grpc.RpcError as e:
            end_ns = self.timer.now_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            return {
                "ok": False,
                "code": e.code().name,
                "latency_ms": round(latency_ms, 2),
                "net_latency_ms": round(latency_ms, 2)
            }
        except Exception as e:
            end_ns = self.timer.now_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            return {
                "ok": False,
                "error": str(e),
                "latency_ms": round(latency_ms, 2),
                "net_latency_ms": round(latency_ms, 2)
            }

    async def run_warmup(self):
        """Run warmup phase with concurrent execution"""
        if self.warmup_sec <= 0:
            return
        logging.info(f"Starting warmup for {self.warmup_sec} seconds at {self.n_rps} RPS")
        interval_sec = 1.0 / self.n_rps
        warmup_start = time.perf_counter()
        next_send_time = warmup_start
        warmup_results = []
        active_tasks = []
        max_concurrent = min(self.n_rps // 2, 100)
        while (time.perf_counter() - warmup_start) < self.warmup_sec:
            current_time = time.perf_counter()
            completed_tasks = [task for task in active_tasks if task.done()]
            for task in completed_tasks:
                try:
                    result = await task
                    warmup_results.append(result)
                except Exception as e:
                    logging.error(f"Warmup task failed: {e}")
            active_tasks = [task for task in active_tasks if not task.done()]
            if current_time >= next_send_time and len(active_tasks) < max_concurrent:
                behind = int((current_time - next_send_time) / interval_sec) + 1
                slots = max_concurrent - len(active_tasks)
                to_send = max(1, min(behind, slots))
                for _ in range(to_send):
                    get_score_fn = self._get_scores[self._rr]
                    self._rr = (self._rr + 1) % max(1, len(self._get_scores))
                    task = asyncio.create_task(self.send_rpc(get_score_fn))
                    active_tasks.append(task)
                    next_send_time += interval_sec
            else:
                sleep_for = max(0.0, next_send_time - current_time)
                await asyncio.sleep(sleep_for if sleep_for > 0 else 0.0005)
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
        interval_sec = 1.0 / self.n_rps
        test_start = time.perf_counter()
        next_send_time = test_start
        active_tasks = []
        max_concurrent = min(self.n_rps // 2, 200)
        while (time.perf_counter() - test_start) < self.duration_sec:
            current_time = time.perf_counter()
            completed_tasks = [task for task in active_tasks if task.done()]
            for task in completed_tasks:
                try:
                    result = await task
                    self.results.append(result)
                except Exception as e:
                    logging.error(f"Task failed: {e}")
                    self.results.append({
                        "ok": False,
                        "code": "TASK_ERROR",
                        "latency_ms": 0.0
                    })
            active_tasks = [task for task in active_tasks if not task.done()]
            if current_time >= next_send_time and len(active_tasks) < max_concurrent:
                behind = int((current_time - next_send_time) / interval_sec) + 1
                slots = max_concurrent - len(active_tasks)
                to_send = max(1, min(behind, slots))
                for _ in range(to_send):
                    get_score_fn = self._get_scores[self._rr]
                    self._rr = (self._rr + 1) % max(1, len(self._get_scores))
                    task = asyncio.create_task(self.send_rpc(get_score_fn))
                    active_tasks.append(task)
                    next_send_time += interval_sec
            else:
                sleep_for = max(0.0, next_send_time - current_time)
                await asyncio.sleep(sleep_for if sleep_for > 0 else 0.0005)
        if active_tasks:
            logging.info(f"Waiting for {len(active_tasks)} remaining tasks to complete...")
            remaining_results = await asyncio.gather(*active_tasks, return_exceptions=True)
            for result in remaining_results:
                if isinstance(result, Exception):
                    logging.error(f"Final task failed: {result}")
                    self.results.append({
                        "ok": False,
                        "code": "TASK_ERROR",
                        "latency_ms": 0.0
                    })
                else:
                    self.results.append(result)
        successful = sum(1 for r in self.results if r["ok"])
        total = len(self.results)
        actual_rps = total / self.duration_sec if self.duration_sec > 0 else 0
        logging.info(f"Load test completed: {successful}/{total} successful RPCs (actual RPS: {actual_rps:.1f})")

    def write_results(self, output_file: str):
        """Write results to JSONL file"""
        try:
            with open(output_file, 'w') as f:
                f.write("#TEST=01_steady\n")
                if not self.results:
                    logging.warning("No per-RPC results collected; writing sentinel record for analysis")
                    self.results.append({
                        "ok": False,
                        "code": "NO_RESULTS",
                        "latency_ms": 0.0
                    })
                for result in self.results:
                    f.write(json.dumps(result) + "\n")
            logging.info(f"Results written to {output_file}")
        except Exception as e:
            logging.error(f"Error writing results: {e}")
            raise


def _extract_server_delay_ms(md, default_value: float) -> float:
    """Extract server delay (ms) from gRPC metadata if present."""
    try:
        if not md:
            return default_value
        md_map = {k.lower(): v for k, v in md}
        val = None
        if 'df-actual-delay-ms' in md_map:
            val = md_map['df-actual-delay-ms']
        elif 'df-config-delay-ms' in md_map:
            val = md_map['df-config-delay-ms']
        if val is None:
            return default_value
        if isinstance(val, (bytes, bytearray)):
            val = val.decode('ascii', errors='ignore')
        return float(val)
    except Exception:
        return default_value


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
    
    host = os.getenv('DF_HOST', '127.0.0.1')
    port = int(os.getenv('DF_PORT', '50051'))
    n_rps = int(os.getenv('N_RPS', '500'))
    duration_sec = int(os.getenv('T_DURATION_SEC', '300'))
    warmup_sec = int(os.getenv('T_WARMUP_SEC', '30'))
    df_delay_ms = float(os.getenv('DF_DELAY_MS', '5.0'))
    tls_ca = os.getenv('TLS_CA', 'certs/ca.crt')
    tls_cert = os.getenv('TLS_CERT', 'certs/client.crt')
    tls_key = os.getenv('TLS_KEY', 'certs/client.key')
    pool_size = int(os.getenv('CHANNEL_POOL_SIZE', '4'))
    
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
        ca_cert, client_cert, client_key, df_delay_ms,
        pool_size=pool_size
    )
    
    try:
        await generator.setup_channel()
        await generator.run_warmup()
        await generator.run_load_test()
    except Exception as e:
        logging.error(f"Load test failed: {e}")
        # Ensure at least one record exists for the summarizer
        try:
            generator.results.append({
                "ok": False,
                "code": "RUN_FAILED",
                "latency_ms": 0.0
            })
        except Exception:
            pass
    finally:
        # Always persist any collected results, even on failure
        try:
            generator.write_results("01_steady_results.txt")
        except Exception as e:
            logging.error(f"Failed to write results: {e}")
        await generator.close_channel()


if __name__ == '__main__':
    # Install uvloop for better performance if available
    if uvloop:
        uvloop.install()
        logging.info("Using uvloop for high-performance event loop")
    
    # Optimize garbage collection for low latency
    gc.disable()  # Disable automatic GC
    gc.set_threshold(0)  # Disable generational GC
    
    # CPU affinity for reduced context switching (Linux only)
    try:
        os.sched_setaffinity(0, {0, 1})  # Pin to cores 0,1
        logging.info("Pinned client to CPU cores 0,1")
    except (AttributeError, OSError):
        pass  # Not available on macOS or permission denied
    
    try:
        asyncio.run(main())
    finally:
        # Manual GC cleanup at end
        gc.collect()
