#!/usr/bin/env python3
"""Simple insecure client for testing"""
import asyncio
import grpc
import score_pb2
import score_pb2_grpc
import json
import time


async def test_client():
    target = "localhost:50052"
    
    async with grpc.aio.insecure_channel(target) as channel:
        stub = score_pb2_grpc.ScoreServiceStub(channel)
        request = score_pb2.JsonVector(json=json.dumps({"test": True}))
        
        print(f"Testing insecure connection to {target}...")
        
        start_time = time.perf_counter()
        response = await stub.GetScore(request)
        end_time = time.perf_counter()
        
        print(f"SUCCESS: Got score {response.score} in {(end_time-start_time)*1000:.2f}ms")


if __name__ == '__main__':
    asyncio.run(test_client())