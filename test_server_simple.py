#!/usr/bin/env python3
"""Simple insecure server for testing"""
import asyncio
import grpc
import score_pb2
import score_pb2_grpc
import random
import logging


class ScoreServicer(score_pb2_grpc.ScoreServiceServicer):
    async def GetScore(self, request, context):
        await asyncio.sleep(0.005)  # 5ms delay
        score = random.uniform(0.0, 1.0)
        logging.info(f"Returning score: {score:.4f}")
        return score_pb2.ScoreResponse(score=score)


async def serve():
    logging.basicConfig(level=logging.INFO)
    server = grpc.aio.server()
    score_pb2_grpc.add_ScoreServiceServicer_to_server(ScoreServicer(), server)
    
    # Use insecure port for testing
    listen_addr = "0.0.0.0:50052"
    server.add_insecure_port(listen_addr)
    
    await server.start()
    logging.info(f"Simple server listening on {listen_addr}")
    
    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        await server.stop(grace=5)


if __name__ == '__main__':
    asyncio.run(serve())