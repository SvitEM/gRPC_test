#!/usr/bin/env python3
"""Debug SSL connection test with detailed logging"""
import asyncio
import grpc
import score_pb2
import score_pb2_grpc
import json
import time
import logging
import os

# Enable grpc debugging
os.environ['GRPC_VERBOSITY'] = 'DEBUG'
os.environ['GRPC_TRACE'] = 'all'

async def test_ssl_connection():
    logging.basicConfig(level=logging.DEBUG)
    
    # Read certificates
    print("Reading certificates...")
    with open('df/certs/ca.crt', 'rb') as f:
        ca_cert = f.read()
    with open('smft/certs/client.crt', 'rb') as f:
        client_cert = f.read()
    with open('smft/certs/client.key', 'rb') as f:
        client_key = f.read()
    
    print("Creating SSL credentials...")
    
    # Try TLS-only credentials (no client auth)
    credentials = grpc.ssl_channel_credentials(
        root_certificates=ca_cert,
        private_key=None,
        certificate_chain=None
    )
    
    target = "localhost:50051"
    print(f"Attempting connection to {target}...")
    
    # Create channel with additional options
    options = [
        ('grpc.keepalive_time_ms', 30000),
        ('grpc.keepalive_timeout_ms', 5000),
        ('grpc.keepalive_permit_without_calls', True),
        ('grpc.http2.max_pings_without_data', 0),
        ('grpc.http2.min_time_between_pings_ms', 10000),
        ('grpc.http2.min_ping_interval_without_data_ms', 300000)
    ]
    
    async with grpc.aio.secure_channel(target, credentials, options=options) as channel:
        try:
            print("Waiting for channel to be ready...")
            await asyncio.wait_for(channel.channel_ready(), timeout=5.0)
            print("Channel ready!")
            
            stub = score_pb2_grpc.ScoreServiceStub(channel)
            request = score_pb2.JsonVector(json=json.dumps({"test": True}))
            
            print("Sending test RPC...")
            response = await stub.GetScore(request, timeout=5.0)
            print(f"SUCCESS: Got score {response.score}")
            
        except asyncio.TimeoutError:
            print("TIMEOUT: Channel failed to become ready")
        except grpc.RpcError as e:
            print(f"RPC ERROR: {e.code()} - {e.details()}")
        except Exception as e:
            print(f"ERROR: {e}")


if __name__ == '__main__':
    asyncio.run(test_ssl_connection())