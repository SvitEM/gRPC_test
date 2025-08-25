#!/usr/bin/env python3
"""Simple connection test without hostname verification"""
import asyncio
import grpc
import score_pb2
import score_pb2_grpc
import json
import time


async def test_connection():
    # Read certificates
    with open('df/certs/ca.crt', 'rb') as f:
        ca_cert = f.read()
    with open('smft/certs/client.crt', 'rb') as f:
        client_cert = f.read()
    with open('smft/certs/client.key', 'rb') as f:
        client_key = f.read()
    
    # Create SSL credentials
    credentials = grpc.ssl_channel_credentials(
        root_certificates=ca_cert,
        private_key=client_key,
        certificate_chain=client_cert
    )
    
    # Test connection
    target = "localhost:50051"
    print(f"Testing connection to {target}...")
    
    async with grpc.aio.secure_channel(target, credentials) as channel:
        try:
            # Wait for channel to be ready
            print("Waiting for channel to be ready...")
            await asyncio.wait_for(channel.channel_ready(), timeout=10.0)
            print("Channel ready!")
            
            # Create stub and test RPC
            stub = score_pb2_grpc.ScoreServiceStub(channel)
            request = score_pb2.JsonVector(json=json.dumps({"test": True}))
            
            print("Sending test RPC...")
            start_time = time.perf_counter()
            response = await stub.GetScore(request)
            end_time = time.perf_counter()
            
            print(f"SUCCESS: Got score {response.score} in {(end_time-start_time)*1000:.2f}ms")
            
        except Exception as e:
            print(f"ERROR: {e}")


if __name__ == '__main__':
    asyncio.run(test_connection())