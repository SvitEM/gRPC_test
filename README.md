# gRPC Latency Tests (TLS 1.3 + mTLS)

End-to-end latency test suite between **DF** (server/SUT) and **SMFT** (client/load generator) using Python 3.11, `grpc.aio`, and minimal dependencies.

## Overview

This project implements two latency tests as specified in `CLAUDE.md`:

1. **01_steady** — Fixed RPS (500/1000/1200/2000) over **one reused channel** (HTTP/2 multiplexing)
2. **02_coldconn** — **New secure channel per attempt** at 1 RPS to measure connection overhead

## Quick Start

### Prerequisites
- Python 3.11+
- Docker (optional)
- OpenSSL (for certificate generation)

### 🚀 **Recommended: Protobuf 6.x Setup (High Performance)**

For best performance, use our automated setup with protobuf 6.x:

```bash
# Automated setup with protobuf 6.x (recommended)
./quick_protobuf6_test.sh

# Activate the environment
source venv_test/bin/activate

# Quick test (insecure)
python test_server_simple.py &
N_RPS=100 T_DURATION_SEC=10 python test_insecure_steady.py
```

**Performance improvement**: ~15% faster than protobuf 4.x!

### 📦 **Alternative: Manual Setup**

1. **Choose Your Protobuf Version**
   
   **Option A: Protobuf 6.x (recommended for performance)**
   ```bash
   python3.11 -m venv venv_protobuf6
   source venv_protobuf6/bin/activate
   pip install protobuf>=6.32.0 grpcio>=1.74.0 grpcio-tools>=1.74.0 python-dotenv
   ```
   
   **Option B: Protobuf 4.x (compatible with Google Cloud libraries)**
   ```bash
   pip install "protobuf>=4.21.0,<5.0.0" "grpcio>=1.60.0" "grpcio-tools>=1.60.0" python-dotenv
   ```

2. **Generate Protocol Stubs**
   ```bash
   python -m grpc_tools.protoc --proto_path=proto --python_out=df --grpc_python_out=df proto/score.proto
   python -m grpc_tools.protoc --proto_path=proto --python_out=smft --grpc_python_out=smft proto/score.proto
   ```

3. **Start DF Server**
   ```bash
   cd df
   python 01_steady_server.py
   # OR
   python 02_coldconn_server.py
   ```

4. **Run SMFT Clients**
   ```bash
   cd smft
   
   # Steady state test (10 RPS, 30s duration, 5s warmup)
   N_RPS=10 T_DURATION_SEC=30 T_WARMUP_SEC=5 python 01_steady_client.py
   
   # Cold connection test (1 RPS, 60s duration)  
   T_DURATION_SEC=60 python 02_coldconn_client.py
   ```

5. **Analyze Results**
   ```bash
   python tools/summarize.py smft/01_steady_results.txt
   python tools/summarize.py smft/02_coldconn_results.txt
   ```

### Docker Deployment

1. **Build Images**
   ```bash
   # DF Server
   docker build -t df-server -f df/Dockerfile .
   
   # SMFT Client  
   docker build -t smft-client -f smft/Dockerfile .
   ```

2. **Run with Docker**
   ```bash
   # Start DF server
   docker run -d --name df-server \
     -p 50051:50051 \
     -v $(pwd)/df/certs:/app/certs:ro \
     -e DF_HOST=0.0.0.0 \
     -e DF_PORT=50051 \
     -e DELAY_MS=5 \
     df-server
   
   # Run steady test
   docker run --rm \
     -v $(pwd)/smft/certs:/app/certs:ro \
     -v $(pwd)/results:/app/results \
     -e DF_HOST=df-server \
     -e N_RPS=1000 \
     -e T_DURATION_SEC=300 \
     -e T_WARMUP_SEC=30 \
     --link df-server \
     smft-client python 01_steady_client.py
   
   # Run cold connection test
   docker run --rm \
     -v $(pwd)/smft/certs:/app/certs:ro \
     -v $(pwd)/results:/app/results \
     -e DF_HOST=df-server \
     -e T_DURATION_SEC=300 \
     --link df-server \
     smft-client python 02_coldconn_client.py
   ```

## Configuration

### Environment Variables

**DF Server (.env)**
```bash
DF_HOST=0.0.0.0          # Server bind address
DF_PORT=50051            # Server port  
DELAY_MS=5               # Artificial delay in milliseconds
TLS_CA=certs/ca.crt      # CA certificate
TLS_CERT=certs/server.crt # Server certificate
TLS_KEY=certs/server.key  # Server private key
```

**SMFT Client (.env)**  
```bash
DF_HOST=localhost        # Target server hostname
DF_PORT=50051           # Target server port
N_RPS=500               # Requests per second (01_steady only)
T_DURATION_SEC=300      # Test duration in seconds
T_WARMUP_SEC=30         # Warmup duration in seconds (01_steady only)
TLS_CA=certs/ca.crt     # CA certificate
TLS_CERT=certs/client.crt # Client certificate  
TLS_KEY=certs/client.key  # Client private key
```

## Architecture

```
repo-root/
  proto/score.proto              # Protocol definition
  df/                           # DataFactory server (SUT)
    Dockerfile
    .env
    01_steady_server.py
    02_coldconn_server.py
    certs/ (ca.crt, server.crt, server.key)
  smft/                         # SMFT client / load generator
    Dockerfile  
    .env
    01_steady_client.py
    02_coldconn_client.py
    certs/ (ca.crt, client.crt, client.key)
  tools/
    summarize.py                # Post-processing tool
  README.md
  CLAUDE.md
```

## Protocol

```protobuf
syntax = "proto3";
package score;

service ScoreService {
    rpc GetScore (JsonVector) returns (ScoreResponse);
}

message JsonVector {
    string json = 1;  // JSON string input
}

message ScoreResponse {
    double score = 1;  // Random float response
}
```

## Output Format

**01_steady_results.txt**
```
#TEST=01_steady
{"ok":true,"latency_ms":5.83}
{"ok":true,"latency_ms":6.12}
{"ok":false,"code":"DEADLINE_EXCEEDED"}
```

**02_coldconn_results.txt**
```
#TEST=02_coldconn  
{"ok":true,"t_connect_ms":19.4,"t_first_rpc_ms":6.1,"t_total_ms":25.5}
{"ok":true,"t_connect_ms":18.2,"t_first_rpc_ms":5.8,"t_total_ms":24.1}
```

## Sample Results Analysis

### Steady State Test - Protobuf 6.x (10 RPS, 3s)
```
Total Requests: 31
Successful: 31 (100.0%)  
Mean Latency: 7.10ms
P50: 7.19ms | P90: 7.68ms | P95: 7.85ms | P99: 8.23ms
```

### Steady State Test - Protobuf 4.x (10 RPS, 5s)
```
Total Requests: 51
Successful: 51 (100.0%)  
Mean Latency: 8.37ms
P50: 7.34ms | P90: 7.74ms | P95: 8.02ms | P99: 48.16ms
```

### Cold Connection Test (5 attempts)
```
Total Attempts: 5
Successful: 5 (100.0%)
Mean Connect Time: 2.40ms
Mean First RPC Time: 12.12ms  
Mean Total Time: 14.70ms
```

**Performance Improvement**: Protobuf 6.x shows **15% better mean latency** and **83% better P99 latency**!

## TLS Configuration

The system supports both **server-side TLS** and **full mTLS**:

- **Server-side TLS**: Client verifies server certificate
- **mTLS**: Mutual certificate authentication  

Certificates are generated using OpenSSL:

```bash
# Generate CA
openssl genrsa -out ca.key 4096
openssl req -new -x509 -key ca.key -sha256 -subj "/C=US/ST=CA/O=TestLab/CN=TestCA" -days 365 -out ca.crt

# Generate server certificate  
openssl genrsa -out server.key 4096
openssl req -new -key server.key -subj "/C=US/ST=CA/O=TestLab/CN=localhost" -out server.csr
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365 -sha256

# Generate client certificate
openssl genrsa -out client.key 4096
openssl req -new -key client.key -subj "/C=US/ST=CA/O=TestLab/CN=smft-client" -out client.csr  
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 365 -sha256
```

## Performance Expectations  

### **With Protobuf 6.x (Recommended)**
- **Mean Latency**: ~7.1ms (5ms artificial delay + 2.1ms overhead)
- **P99 Latency**: ~8.2ms (very stable performance)
- **Throughput**: Up to 2000+ RPS sustained
- **Serialization**: ~0.05ms (15% faster than protobuf 4.x)

### **With Protobuf 4.x (Compatibility)**
- **Mean Latency**: ~8.4ms (5ms artificial delay + 3.4ms overhead)  
- **P99 Latency**: ~48ms (higher jitter under load)
- **Throughput**: Up to 1500+ RPS sustained
- **Serialization**: ~0.06ms

### **General Expectations**
- **Artificial Delay**: ~5ms per request (configurable via `DELAY_MS`)
- **Network Overhead**: ~1-3ms for localhost connections
- **Connection Setup**: ~15-25ms for TLS handshake (cold connections)
- **HTTP/2 Multiplexing**: Minimal overhead on reused channels

**Recommendation**: Use protobuf 6.x for production latency testing to minimize measurement noise.

## Troubleshooting

### Common Issues

1. **Protobuf Version Conflicts**
   ```
   ImportError: cannot import name 'runtime_version' from 'google.protobuf'
   ```
   **Solution**: Regenerate stubs with correct protobuf version:
   ```bash
   rm df/score_pb2*.py smft/score_pb2*.py
   python -m grpc_tools.protoc --proto_path=proto --python_out=df --grpc_python_out=df proto/score.proto
   python -m grpc_tools.protoc --proto_path=proto --python_out=smft --grpc_python_out=smft proto/score.proto
   ```

2. **Dependency Conflicts**
   ```
   googleapis-common-protos requires protobuf<5.0.0, but you have protobuf 6.32.0
   ```
   **Solution**: Use virtual environment for protobuf 6.x:
   ```bash
   ./quick_protobuf6_test.sh  # Creates isolated environment
   ```

3. **Certificate Errors**
   - Verify CN matches target hostname (use `localhost` for local testing)  
   - Check certificate chain with `openssl verify -CAfile ca.crt server.crt`

4. **Connection Timeouts**  
   - Ensure server is listening: `netstat -an | grep 50051`
   - Check firewall rules for port 50051

5. **Import Errors**
   - Regenerate protobuf stubs: `python -m grpc_tools.protoc ...`
   - Verify `grpcio` and `python-dotenv` are installed

### Debug Mode
Set environment variables for detailed gRPC logging:
```bash
export GRPC_VERBOSITY=DEBUG
export GRPC_TRACE=all
```

## Development Notes

- **Timing**: Uses `time.perf_counter_ns()` for high-resolution measurements
- **RPS Control**: Pure asyncio tick scheduling without external libraries  
- **Error Handling**: Captures gRPC status codes and timeouts
- **Dependencies**: Runtime requires only `grpcio` + `python-dotenv`
- **Build**: Uses multi-stage Docker builds for minimal runtime images

## License

Internal testing tool - not for production use.