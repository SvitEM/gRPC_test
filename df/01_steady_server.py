#!/usr/bin/env python3
"""
DF Steady Server - gRPC server with mTLS and artificial delay
"""
import asyncio
import logging
import time
from concurrent import futures
import os
import random
import sys
from pathlib import Path

# Ensure high-performance protobuf implementation is selected early
os.environ.setdefault('PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION', 'upb')

# Optimize protobuf implementation for best performance (optional)
try:
    from protobuf_optimizer import optimize_protobuf
    optimize_protobuf()
except ImportError:
    pass

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


class ScoreServicer(score_pb2_grpc.ScoreServiceServicer):
    """ScoreService implementation with artificial delay"""
    
    def __init__(self, delay_ms: float):
        self.delay_seconds = delay_ms / 1000.0
        logging.info(f"ScoreServicer initialized with {delay_ms}ms delay")
        # Prebind hot-path callables to reduce lookups/allocs per request
        self._sleep = asyncio.sleep
        self._rand = random.random
        self._mk_resp = score_pb2.ScoreResponse
        
    async def GetScore(self, request: score_pb2.JsonVector, context: grpc.ServicerContext) -> score_pb2.ScoreResponse:
        """Handle GetScore RPC with artificial delay"""
        try:
            # Add artificial delay
            if self.delay_seconds > 0:
                start_ns = time.perf_counter_ns()
                await self._sleep(self.delay_seconds)
                actual_delay_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            else:
                actual_delay_ms = 0.0

            # If the client cancelled or deadline exceeded, stop cleanly
            if hasattr(context, "is_active") and not context.is_active():
                await context.abort(grpc.StatusCode.CANCELLED, "Request cancelled or deadline exceeded")

            # Send initial metadata with configured and actual delay for precise client-side accounting
            try:
                await context.send_initial_metadata((
                    ("df-config-delay-ms", f"{self.delay_seconds * 1000.0:.3f}"),
                    ("df-actual-delay-ms", f"{actual_delay_ms:.3f}"),
                ))
            except Exception:
                # Ignore metadata send issues; proceed with response
                pass

            # Create fresh response instead of reusing (fixes ExecuteBatchError)
            return self._mk_resp(score=self._rand())
            
        except asyncio.CancelledError:
            # Handle client disconnection gracefully
            logging.debug("Request cancelled by client")
            raise
        except grpc.RpcError:
            # Propagate aborts/cancellations without converting to INTERNAL
            raise
        except Exception as e:
            logging.exception(f"Error processing GetScore request: {e}")
            # Abort the RPC with INTERNAL to avoid partial writes on closed streams
            await context.abort(grpc.StatusCode.INTERNAL, "Internal server error")


async def serve():
    """Start the gRPC server with mTLS configuration"""
    # Load environment configuration
    load_dotenv()
    
    host = os.getenv('DF_HOST', '0.0.0.0')
    port = int(os.getenv('DF_PORT', '50051'))
    # Default to no artificial delay; set DELAY_MS if needed explicitly
    delay_ms = float(os.getenv('DELAY_MS', '0'))
    tls_ca = os.getenv('TLS_CA', 'certs/ca.crt')
    tls_cert = os.getenv('TLS_CERT', 'certs/server.crt')
    tls_key = os.getenv('TLS_KEY', 'certs/server.key')
    
    logging.info(f"Starting DF Steady Server on {host}:{port} with {delay_ms}ms delay")
    
    # Validate certificate files exist
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
            server_cert = f.read()
        with open(tls_key, 'rb') as f:
            server_key = f.read()
    except Exception as e:
        logging.error(f"Error reading certificate files: {e}")
        sys.exit(1)
    
    # Create SSL server credentials with mTLS (require client auth)
    server_credentials = grpc.ssl_server_credentials(
        [(server_key, server_cert)],
        root_certificates=ca_cert,
        require_client_auth=True
    )
    
    # Create and configure server with optimized settings (pure-async handlers)
    server = grpc.aio.server(
        options=(
            ('grpc.so_reuseport', 1),
            ('grpc.max_concurrent_streams', 512),    # Match client limit
            ('grpc.keepalive_time_ms', 30000),       # 30 sec keepalive
            ('grpc.keepalive_timeout_ms', 5000),     # 5 sec timeout
            ('grpc.keepalive_permit_without_calls', True),
            ('grpc.http2.max_pings_without_data', 0),
            ('grpc.http2.min_time_between_pings_ms', 10000),  # 10 sec
            ('grpc.http2.min_ping_interval_without_data_ms', 10000), # 10 sec
            ('grpc.max_receive_message_length', 1048576),  # 1MB limit
            ('grpc.max_send_message_length', 1048576),     # 1MB limit
            # TCP buffer optimization
            ('grpc.so_sndbuf', 1048576),          # 1MB send buffer
            ('grpc.so_rcvbuf', 1048576),          # 1MB recv buffer
            ('grpc.http2.bdp_probe', 0),          # Disable BDP probe on loopback
            ('grpc.http2.max_frame_size', 16777215), # Max frame size
            # Increase HTTP/2 flow-control windows
            ('grpc.http2.initial_connection_window_size', 8388608),
            ('grpc.http2.initial_stream_window_size', 8388608),
        ),
    )
    score_pb2_grpc.add_ScoreServiceServicer_to_server(
        ScoreServicer(delay_ms), server
    )
    
    # Add secure port with mTLS
    listen_addr = f'{host}:{port}'
    server.add_secure_port(listen_addr, server_credentials)
    
    # Start server
    await server.start()
    logging.info(f"DF Steady Server listening on {listen_addr} (mTLS enabled)")
    
    # Background GC maintainer removed to avoid any periodic pauses
    from contextlib import suppress
    gc_task = None
    
    # Wait for termination
    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        logging.info("Received interrupt signal, shutting down...")
    finally:
        logging.info("Stopping server...")
        if gc_task is not None:
            gc_task.cancel()
            with suppress(asyncio.CancelledError):
                await gc_task
        await server.stop(grace=2)
        logging.info("Server shutdown complete")


def setup_logging():
    """Configure logging"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def main():
    """Main entry point"""
    setup_logging()
    
    # Install uvloop for better performance if available
    if uvloop:
        uvloop.install()
        logging.info("Using uvloop for high-performance event loop")
    
    # Optimize garbage collection for ultra-low latency: disable completely
    import gc
    gc.disable()
    gc.set_threshold(0)
    
    # Log detailed protobuf status
    try:
        from protobuf_optimizer import log_protobuf_status
        log_protobuf_status(logging.getLogger())
    except ImportError:
        logging.warning("Could not import protobuf optimizer")
    
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        logging.info("Server stopped by user")
    except Exception as e:
        logging.error(f"Server error: {e}")
        sys.exit(1)
    finally:
        gc.collect()  # Final cleanup


if __name__ == '__main__':
    main()
