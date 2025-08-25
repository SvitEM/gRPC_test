# SMFT (Smart Manufacturing Test) Client Dockerfile
# Multi-stage build: generate stubs at build-time, minimal runtime image

FROM python:3.11-slim as builder

# Install build-time dependencies
RUN pip install --no-cache-dir grpcio-tools

# Copy proto files
COPY ../proto/score.proto /app/proto/

# Generate protobuf stubs
WORKDIR /app
RUN python -m grpc_tools.protoc \
    --proto_path=proto \
    --python_out=. \
    --grpc_python_out=. \
    proto/score.proto

# Runtime image
FROM python:3.11-slim

# Install runtime dependencies only
RUN pip install --no-cache-dir grpcio python-dotenv

# Create app directory
WORKDIR /app

# Copy generated stubs from builder
COPY --from=builder /app/score_pb2.py /app/score_pb2_grpc.py ./

# Copy client code
COPY *.py ./

# Create non-root user for security
RUN useradd -r -s /bin/false appuser
USER appuser

# Default environment (can be overridden by .env or docker run -e)
ENV DF_HOST=df-server
ENV DF_PORT=50051
ENV N_RPS=500
ENV T_DURATION_SEC=300
ENV T_WARMUP_SEC=30
ENV TLS_CA=certs/ca.crt
ENV TLS_CERT=certs/client.crt
ENV TLS_KEY=certs/client.key

# Entry point - default to steady client
CMD ["python", "01_steady_client.py"]