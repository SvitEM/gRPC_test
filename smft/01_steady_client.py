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
from collections import deque

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

# Import transaction generator  
from generator import generate_transaction_json, generate_transaction_event_sync

def generate_transaction_json_sync():
    """Fast synchronous transaction generation"""
    event = generate_transaction_event_sync()
    return json.dumps(event)

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
        # Ensure pool size is power of 2 for bitwise optimization
        self.pool_size = max(1, 1 << (int(pool_size) - 1).bit_length())
        self.pool_mask = self.pool_size - 1  # Bitwise mask for round-robin
        
        # Create SSL credentials with mTLS (client certs)
        self.credentials = grpc.ssl_channel_credentials(
            root_certificates=ca_cert,
            private_key=client_key,
            certificate_chain=client_cert
        )
        
        # Ultra-optimized gRPC options for <10ms overhead with 50ms timeout
        self.channel_options = [
            ('grpc.keepalive_time_ms', 300000),      # 5min - minimal overhead
            ('grpc.keepalive_timeout_ms', 30000),    # 30s timeout
            ('grpc.keepalive_permit_without_calls', False), # No unnecessary keepalives
            ('grpc.http2.max_pings_without_data', 0),
            ('grpc.http2.min_ping_interval_without_data_ms', 30000), # Reduce ping frequency
            ('grpc.http2.min_time_between_pings_ms', 30000),
            ('grpc.max_send_message_length', 65536),     # 64KB - smaller for speed
            ('grpc.max_receive_message_length', 4096),   # 4KB - minimal response size
            ('grpc.max_concurrent_streams', 1000),       # Adequate for load
            ('grpc.so_sndbuf', 65536),                   # 64KB buffers - smaller/faster
            ('grpc.so_rcvbuf', 65536),                   
            ('grpc.http2.bdp_probe', 0),                 # Disable BDP probing - overhead
            ('grpc.http2.max_frame_size', 16384),        # 16KB frames - faster processing
            ('grpc.http2.write_buffer_size', 8192),      # 8KB write buffer - minimal
            ('grpc.http2.initial_connection_window_size', 65536),   # 64KB windows
            ('grpc.http2.initial_stream_window_size', 65536),
            ('grpc.enable_http_proxy', 0),               # Disable proxy detection
            ('grpc.use_local_subchannel_pool', 1),       # Optimize connection reuse
            ('grpc.http2.lookahead_bytes', 0),           # Disable lookahead - overhead
            ('grpc.http2.hpack_table_size.decoder', 4096), # Smaller tables
            ('grpc.http2.hpack_table_size.encoder', 4096),
            ('grpc.optimization.disable_call_batching', 1),  # Disable batching for low latency
        ]
        
        self.results: List[Dict] = []
        self.channels: List[grpc.aio.Channel] = []
        self.stubs: List[score_pb2_grpc.ScoreServiceStub] = []
        self._get_scores = []
        self._rr = 0
        
        # Pre-generate transaction data for better performance
        self._transaction_cache = []
        self._cache_index = 0
        
        # High-resolution timer for reduced system call overhead
        self.timer = HighResTimer()
        
        # Adaptive timeout management to reduce DEADLINE_EXCEEDED errors
        self.base_timeout_ms = 50.0
        self.adaptive_timeout_ms = self.base_timeout_ms
        self.recent_latencies = deque(maxlen=100)  # Rolling window for timeout adaptation
        self.timeout_adaptation_interval = 2000  # Adapt every N requests (less frequent)
        self.requests_since_adaptation = 0
        
        # Connection health monitoring
        self.connection_errors = deque(maxlen=50)  # Track recent connection issues
        self.health_check_interval = 10000  # Check health every N requests (less frequent)
        self.requests_since_health_check = 0
        self.unhealthy_threshold = 0.20  # 20% error rate triggers recovery (much higher)
        
        # Circuit breaker pattern for overload protection - more conservative thresholds
        self.circuit_breaker_enabled = False
        self.circuit_open_threshold = 0.50  # 50% error rate opens circuit (much higher)
        self.circuit_reset_time = 5.0  # Reset after 5 seconds (faster recovery)
        self.circuit_opened_at = 0.0
        self.recent_error_rate = 0.0
        
        # Removed priority logic for performance
    
    async def setup_channel(self):
        """Create and configure the reused secure channel"""
        logging.info(f"Creating {self.pool_size} secure channel(s) to {self.target}")
        for _ in range(self.pool_size):
            ch = grpc.aio.secure_channel(self.target, self.credentials, options=self.channel_options)
            self.channels.append(ch)
            stub = score_pb2_grpc.ScoreServiceStub(ch)
            self.stubs.append(stub)
            self._get_scores.append(stub.GetScore)
            
        # Pre-generate transaction cache for better performance
        cache_size = min(10000, max(1000, self.n_rps * 10))
        logging.info(f"Pre-generating {cache_size} transaction events...")
        for _ in range(cache_size):
            transaction_json = generate_transaction_json_sync()  # Use sync version for speed
            self._transaction_cache.append(score_pb2.JsonVector(json=transaction_json))
        logging.info(f"Transaction cache ready with {len(self._transaction_cache)} events")
            
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
    
    def adapt_timeout(self):
        """Adapt timeout based on recent latency patterns"""
        if len(self.recent_latencies) < 50:  # Need enough samples
            return
            
        # Calculate percentiles from recent latencies
        sorted_latencies = sorted(self.recent_latencies)
        p95_idx = int(0.95 * len(sorted_latencies))
        p95_latency = sorted_latencies[p95_idx]
        
        # More conservative adaptive timeout: P95 + server delay + 50% buffer
        target_timeout = (p95_latency + self.df_delay_ms) * 1.5
        
        # Keep timeout within reasonable bounds (40ms - 80ms) - tighter range
        self.adaptive_timeout_ms = max(40.0, min(80.0, target_timeout))
        
        # Reset adaptation counter
        self.requests_since_adaptation = 0

    async def check_connection_health(self):
        """Monitor connection health and trigger recovery if needed"""
        if len(self.connection_errors) < 50:  # Need enough samples - more conservative
            return
            
        error_rate = sum(1 for error in self.connection_errors if error) / len(self.connection_errors)
        
        if error_rate > self.unhealthy_threshold:
            logging.warning(f"Connection health degraded: {error_rate:.1%} error rate, attempting recovery...")
            
            # Attempt connection recovery
            try:
                # Quick health check on all channels
                health_tasks = []
                for channel in self.channels:
                    # Use channel_ready with short timeout as health check
                    health_task = asyncio.wait_for(channel.channel_ready(), timeout=1.0)
                    health_tasks.append(health_task)
                
                # Wait for all health checks
                await asyncio.gather(*health_tasks, return_exceptions=True)
                logging.info("Connection health check completed")
                
            except Exception as e:
                logging.warning(f"Connection recovery failed: {e}")
        
        # Reset health check counter
        self.requests_since_health_check = 0

    def check_circuit_breaker(self):
        """Check and manage circuit breaker state"""
        if len(self.connection_errors) < 100:  # Need more samples to avoid false positives
            return False  # Not enough samples
            
        current_time = time.perf_counter()
        error_rate = sum(1 for error in self.connection_errors if error) / len(self.connection_errors)
        self.recent_error_rate = error_rate
        
        # Check if circuit should open
        if not self.circuit_breaker_enabled and error_rate > self.circuit_open_threshold:
            self.circuit_breaker_enabled = True
            self.circuit_opened_at = current_time
            logging.warning(f"Circuit breaker OPENED due to {error_rate:.1%} error rate")
            return True
            
        # Check if circuit should reset
        if self.circuit_breaker_enabled:
            if current_time - self.circuit_opened_at > self.circuit_reset_time:
                self.circuit_breaker_enabled = False
                logging.info("Circuit breaker CLOSED - attempting recovery")
                return False
            return True  # Circuit still open
            
        return False

    async def send_rpc_priority(self, get_score_fn, timeout_sec) -> Dict:
        """Send RPC with priority timeout for catch-up scenarios"""
        
        # Check circuit breaker first
        if self.check_circuit_breaker():
            return {
                "ok": False,
                "code": "CIRCUIT_OPEN",
                "latency_ms": 0.0,
                "net_latency_ms": 0.0
            }
        
        start_ns = self.timer.now_ns()
        
        try:
            # Get transaction from cache
            request = self._transaction_cache[self._cache_index]
            self._cache_index = (self._cache_index + 1) % len(self._transaction_cache)

            # Use priority timeout
            _ = await get_score_fn(
                request,
                timeout=timeout_sec,
                compression=grpc.Compression.NoCompression
            )
            
            end_ns = self.timer.now_ns()
            total_latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            # Track latency and health
            self.recent_latencies.append(total_latency_ms)
            self.requests_since_adaptation += 1
            self.requests_since_health_check += 1
            self.connection_errors.append(False)
            
            # Periodic maintenance (less frequent for priority requests)
            if self.requests_since_adaptation >= self.timeout_adaptation_interval:
                self.adapt_timeout()
            if self.requests_since_health_check >= self.health_check_interval:
                await self.check_connection_health()
            
            net_latency_ms = max(0.0, total_latency_ms - self.df_delay_ms)
            
            return {
                "ok": True,
                "latency_ms": round(total_latency_ms, 3),
                "net_latency_ms": round(net_latency_ms, 3)
            }
            
        except grpc.RpcError as e:
            end_ns = self.timer.now_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            self.connection_errors.append(True)
            self.requests_since_health_check += 1
            
            return {
                "ok": False,
                "code": e.code().name,
                "latency_ms": round(latency_ms, 3),
                "net_latency_ms": round(latency_ms, 3)
            }
        except Exception:
            end_ns = self.timer.now_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            self.connection_errors.append(True)
            self.requests_since_health_check += 1
            
            return {
                "ok": False,
                "code": "UNKNOWN_ERROR", 
                "latency_ms": round(latency_ms, 3),
                "net_latency_ms": round(latency_ms, 3)
            }

    async def send_rpc(self, get_score_fn=None) -> Dict:
        """Send single RPC with strict 50ms deadline - abandon if exceeded"""
        
        start_ns = self.timer.now_ns()
        deadline_ns = start_ns + 50_000_000  # 50ms in nanoseconds
        
        try:
            # Pick method via round-robin if not provided (bitwise optimized)
            if get_score_fn is None:
                get_score_fn = self._get_scores[self._rr & self.pool_mask]
                self._rr += 1

            # Get transaction from cache with round-robin
            request = self._transaction_cache[self._cache_index]
            self._cache_index = (self._cache_index + 1) % len(self._transaction_cache)

            # Use strict 50ms timeout with deadline enforcement
            timeout_sec = 0.050  # Fixed 50ms timeout

            # Create the call object and await response with deadline check
            rpc_call = get_score_fn(
                request,
                timeout=timeout_sec,
                compression=grpc.Compression.NoCompression
            )
            
            # Wait for response but check deadline periodically
            _ = await asyncio.wait_for(rpc_call, timeout=timeout_sec)
            
            end_ns = self.timer.now_ns()
            total_latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            # Check if we exceeded deadline (should not happen with proper timeout)
            if end_ns > deadline_ns:
                return {
                    "ok": False,
                    "code": "DEADLINE_EXCEEDED_POST",
                    "latency_ms": round(total_latency_ms, 3),
                    "net_latency_ms": round(total_latency_ms, 3)
                }
            
            # Calculate net latency (subtract server delay)
            net_latency_ms = max(0.0, total_latency_ms - self.df_delay_ms)
            
            return {
                "ok": True,
                "latency_ms": round(total_latency_ms, 3),
                "net_latency_ms": round(net_latency_ms, 3)
            }
        except grpc.RpcError as e:
            end_ns = self.timer.now_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            # Fast error path - minimal overhead
            return {
                "ok": False,
                "code": e.code().name,
                "latency_ms": round(latency_ms, 3),
                "net_latency_ms": round(latency_ms, 3)
            }
        except Exception:
            # Fastest error path - minimal processing
            end_ns = self.timer.now_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000.0
            
            return {
                "ok": False,
                "code": "UNKNOWN_ERROR", 
                "latency_ms": round(latency_ms, 3),
                "net_latency_ms": round(latency_ms, 3)
            }

    async def run_warmup(self):
        """Run warmup phase with concurrent execution"""
        if self.warmup_sec <= 0:
            return
        # Minimize logging during hot path - cache messages
        warmup_msg = f"Starting warmup for {self.warmup_sec} seconds at {self.n_rps} RPS"
        logging.info(warmup_msg)
        interval_sec = 1.0 / self.n_rps
        warmup_start = time.perf_counter()
        next_send_time = warmup_start
        warmup_results = []
        active_tasks = deque()  # Use deque for O(1) operations
        max_concurrent = min(self.n_rps, 2000)  # Higher concurrency for high RPS
        
        while (time.perf_counter() - warmup_start) < self.warmup_sec:
            current_time = time.perf_counter()
            
            # Batch process completed tasks
            remaining_tasks = deque()
            while active_tasks:
                task = active_tasks.popleft()
                if task.done():
                    try:
                        result = task.result()
                        warmup_results.append(result)
                    except Exception:
                        pass  # Ignore warmup failures
                else:
                    remaining_tasks.append(task)
            active_tasks = remaining_tasks
            if current_time >= next_send_time and len(active_tasks) < max_concurrent:
                behind = int((current_time - next_send_time) / interval_sec) + 1
                slots = max_concurrent - len(active_tasks)
                to_send = max(1, min(behind, slots))
                
                # Skip priority logic - just send requests
                
                for _ in range(to_send):
                    get_score_fn = self._get_scores[self._rr & self.pool_mask]
                    self._rr += 1
                    
                    # Create task and mark start time for deadline tracking
                    task = asyncio.create_task(self.send_rpc(get_score_fn))
                    task._start_time_ns = time.perf_counter_ns()  # Track start time
                    
                    active_tasks.append(task)
                    next_send_time += interval_sec
            else:
                sleep_for = max(0.0, next_send_time - current_time)
                if sleep_for > 0.001:  # Only sleep if > 1ms
                    await asyncio.sleep(sleep_for)
                elif len(active_tasks) > max_concurrent * 0.8:  # High load condition
                    # Under high load, yield more aggressively to prevent queuing
                    await asyncio.sleep(0.0001)  # 0.1ms micro-sleep
                else:
                    await asyncio.sleep(0)  # Yield control without delay
        if active_tasks:
            remaining_results = await asyncio.gather(*list(active_tasks), return_exceptions=True)
            for result in remaining_results:
                if not isinstance(result, Exception):
                    warmup_results.append(result)
        successful = sum(1 for r in warmup_results if r["ok"])
        logging.info(f"Warmup completed: {successful}/{len(warmup_results)} successful RPCs")

    async def run_load_test(self):
        """Run the main load test phase with concurrent RPC execution"""
        # Cache log message to avoid string formatting in hot path
        load_msg = f"Starting load test for {self.duration_sec} seconds at {self.n_rps} RPS"
        logging.info(load_msg)
        interval_sec = 1.0 / self.n_rps
        test_start = time.perf_counter()
        next_send_time = test_start
        active_tasks = deque()  # Use deque for O(1) operations
        max_concurrent = min(self.n_rps, 2000)  # Higher concurrency for 2000 RPS
        
        # Pre-allocate error result to avoid repeated dict creation
        error_result = {
            "ok": False,
            "code": "TASK_ERROR", 
            "latency_ms": 0.0
        }
        
        while (time.perf_counter() - test_start) < self.duration_sec:
            current_time = time.perf_counter()
            
            # Batch process completed tasks with deadline enforcement
            completed_count = 0
            remaining_tasks = deque()
            current_time_ns = time.perf_counter_ns()
            
            while active_tasks:
                task = active_tasks.popleft()
                if task.done():
                    completed_count += 1
                    try:
                        result = task.result()  # Use result() instead of await for done tasks
                        self.results.append(result)
                    except Exception:
                        self.results.append(error_result.copy())
                else:
                    # Check if task has been running too long (>50ms)
                    task_start_time = getattr(task, '_start_time_ns', current_time_ns)
                    if (current_time_ns - task_start_time) > 50_000_000:  # 50ms in nanoseconds
                        # Cancel slow task and record as timeout
                        task.cancel()
                        self.results.append({
                            "ok": False,
                            "code": "DEADLINE_ABANDONED",
                            "latency_ms": 50.0,
                            "net_latency_ms": 50.0
                        })
                    else:
                        remaining_tasks.append(task)
            
            active_tasks = remaining_tasks
            if current_time >= next_send_time and len(active_tasks) < max_concurrent:
                behind = int((current_time - next_send_time) / interval_sec) + 1
                slots = max_concurrent - len(active_tasks)
                to_send = max(1, min(behind, slots))
                
                # Skip priority logic - just send requests
                
                for _ in range(to_send):
                    get_score_fn = self._get_scores[self._rr & self.pool_mask]
                    self._rr += 1
                    
                    # Create task and mark start time for deadline tracking
                    task = asyncio.create_task(self.send_rpc(get_score_fn))
                    task._start_time_ns = time.perf_counter_ns()  # Track start time
                    
                    active_tasks.append(task)
                    next_send_time += interval_sec
            else:
                sleep_for = max(0.0, next_send_time - current_time)
                if sleep_for > 0.001:  # Only sleep if > 1ms
                    await asyncio.sleep(sleep_for)
                elif len(active_tasks) > max_concurrent * 0.8:  # High load condition
                    # Under high load, yield more aggressively to prevent queuing
                    await asyncio.sleep(0.0001)  # 0.1ms micro-sleep
                else:
                    await asyncio.sleep(0)  # Yield control without delay
        if active_tasks:
            logging.info(f"Waiting for {len(active_tasks)} remaining tasks to complete...")
            remaining_results = await asyncio.gather(*list(active_tasks), return_exceptions=True)
            for result in remaining_results:
                if isinstance(result, Exception):
                    self.results.append(error_result.copy())
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
    
    # Cache formatted log strings to avoid string operations in hot path
    start_msg = f"SMFT Steady Client starting - Target: {host}:{port}, RPS: {n_rps}, Duration: {duration_sec}s, Warmup: {warmup_sec}s, DF Delay: {df_delay_ms}ms"
    logging.info(start_msg)
    
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
    
    # Enhanced CPU affinity and performance tuning
    try:
        import psutil
        # Get performance cores (typically first cores on modern systems)
        cpu_count = psutil.cpu_count(logical=False)  # Physical cores only
        if cpu_count >= 4:
            # Use first 2 performance cores, avoid hyperthreads
            performance_cores = {0, 1}
        else:
            # Fallback for systems with fewer cores
            performance_cores = {0}
        
        os.sched_setaffinity(0, performance_cores)
        logging.info(f"Pinned client to performance cores: {performance_cores}")
        
        # Set high priority for better scheduling
        try:
            os.nice(-10)  # Higher priority (requires privileges on some systems)
            logging.info("Set high process priority")
        except (OSError, PermissionError):
            pass
            
    except (AttributeError, OSError, ImportError):
        # Fallback to original logic
        try:
            os.sched_setaffinity(0, {0, 1})
            logging.info("Pinned client to CPU cores 0,1 (fallback)")
        except (AttributeError, OSError):
            pass
    
    try:
        asyncio.run(main())
    finally:
        # Manual GC cleanup at end
        gc.collect()
