# DF (DataFactory) Server Dockerfile
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

# Copy server code
COPY *.py ./

# Create non-root user for security
RUN useradd -r -s /bin/false appuser
USER appuser

# Default environment (can be overridden by .env or docker run -e)
ENV DF_HOST=0.0.0.0
ENV DF_PORT=50051
ENV DELAY_MS=5
ENV TLS_CA=certs/ca.crt
ENV TLS_CERT=certs/server.crt
ENV TLS_KEY=certs/server.key

# Expose port
EXPOSE 50051

# Entry point
CMD ["python", "01_steady_server.py"]