# Project: gRPC Latency Tests (TLS 1.3 + mTLS)

## Purpose

End-to-end design and execution of two latency tests between **DF** (server/SUT) and **SMFT** (client/load generator) using **Python 3.11** and **`grpc.aio`** with **TLS 1.3 + mTLS** and **minimal dependencies**.

**Tests**

1. **01_steady** — fixed 500/1000/1200/2000 RPS over **one reused channel** (HTTP/2 multiplexing). Measure steady-state end‑to‑end latencies.
2. **02_coldconn** — **new secure channel per attempt** at 1 RPS. Measure `T_connect` (TCP+TLS+HTTP/2 handshake), `T_first_rpc`, `T_total`.

---

## Repository layout

```
repo-root/
  proto/score.proto
  df/                      # DataFactory server (SUT)
    Dockerfile
    .env
    01_steady_server.py
    02_coldconn_server.py
    certs/ (ca.crt, server.crt, server.key)
  smft/                    # SMFT client / load generator
    Dockerfile
    .env
    01_steady_client.py
    02_coldconn_client.py
    certs/ (ca.crt, client.crt, client.key)
  README.md
  CLAUDE.md
```

---

## Hard requirements

- **Artificial \~5 ms latency** on DF response path (default via `asyncio.sleep(DELAY_MS)` in server handler).
  _(Optionally, network delay via `tc netem`; default remains app‑level sleep for determinism.)_
- **TLS 1.3 + mTLS** end-to-end (client and server certs, root CA).
- **Minimal runtime dependencies**: `grpcio` only. Build-time: `grpcio-tools` for stub generation.
- **Test 1 (01_steady)**: reuse **one** `secure_channel` for all RPCs (HTTP/2 multiplexing).
- **Test 2 (02_coldconn)**: create **new** `secure_channel` for each attempt; measure handshake + first RPC.
- **Outputs**: plain text `.txt` per test with **one JSON record per line** (JSONL). First line must include a header with the test name, e.g. `#TEST=01_steady`.
- **File prefixes**: Paired files share the same numeric prefix (`01_*`, `02_*`) so they can be launched together.
- **Env-driven config** via `.env` in **each** service:

  - **DF**: `DF_HOST`, `DF_PORT`, `DELAY_MS`, `TLS_CA`, `TLS_CERT`, `TLS_KEY`.
  - **SMFT**: `DF_HOST`, `DF_PORT`, `N_RPS`, `T_DURATION_SEC`, `T_WARMUP_SEC`, `TLS_CA`, `TLS_CERT`, `TLS_KEY`.

---

## Protocol

`proto/score.proto`:

```proto
syntax = "proto3";
package score;
service ScoreService { rpc GetScore (JsonVector) returns (ScoreResponse); }
message JsonVector  { string json  = 1; }    // random vector (JSON string)
message ScoreResponse { double score = 1; }  // random float reply
```

---

## Runbook (minimal tooling)

**Build**

- Generate stubs with `grpcio-tools` during Docker build; copy only generated `*_pb2*.py` into the runtime image.

**DF (server)**

- Start `grpc.aio` server on `${DF_HOST}:${DF_PORT}` with mTLS (`ssl_server_credentials`).
- In the RPC handler: parse JSON string (optional), **`await asyncio.sleep(DELAY_MS/1000.0)`**, return random `ScoreResponse`.

**SMFT (client)**

- Common TLS: load `ca.crt`, `client.crt`, `client.key`; use `grpc.ssl_channel_credentials`.
- **01_steady**: create **one** `secure_channel` and `stub`; warm up `T_WARMUP_SEC`; hold **`N_RPS`** precisely for `T_DURATION_SEC` using pure‑`asyncio` tick scheduling; record per‑RPC latency (`perf_counter_ns()` → ms); write JSONL to `01_steady_results.txt`.
- **02_coldconn**: loop at **1 RPS**; for each iteration: create channel → `await channel_ready()` → perform first RPC (`wait_for_ready=True`) → close channel; write JSONL with `t_connect_ms`, `t_first_rpc_ms`, `t_total_ms` to `02_coldconn_results.txt`.

**RPS control**

- Implement token/tick scheduling in pure `asyncio` (no extra libs).

**Timing**

- Use `time.perf_counter_ns()` (monotonic, high‑resolution) for all measurements.

---

## Output format (examples)

- `smft/01_steady_results.txt`:

  - line0: `#TEST=01_steady`
  - lines: `{"ok":true,"latency_ms":5.83}` or `{"ok":false,"code":"DEADLINE_EXCEEDED"}`

- `smft/02_coldconn_results.txt`:

  - line0: `#TEST=02_coldconn`
  - lines: `{"ok":true,"t_connect_ms":19.4,"t_first_rpc_ms":6.1,"t_total_ms":25.5}`

---

## Acceptance criteria

- **Latency**: compute p50/p90/p95/p99/p99.9 and max from result files (post‑processing may be a stdlib‑only script).
- **Throughput** (steady-state): achieved successful RPC/s ≈ `N_RPS` after warm‑up.
- **Error rate**: per‑status share (no auto‑retries during tests).
- **Reproducibility**: both tests run from Docker with only `grpcio` at runtime.

---

## Safety & agent guardrails

- Follow small, explicit steps: _plan → implement → run → verify → commit_.
- Narrow tool allowlist (Edit; Bash for `python`, `pip`, `docker`, `git`, `protoc`).
- No destructive file ops or mass cleanups without explicit human approval.
- Do **not** commit secrets. Local certs live under `df/certs/` and `smft/certs/` or are mounted at runtime.
- If using `tc netem` for network delay, require `--cap-add NET_ADMIN` and document exact commands. Default stays with `asyncio.sleep`.

---

## Multi‑Claude / agent roles

- **Tech Lead Agent** — own scope, constraints, acceptance criteria; publish task board; enforce minimal tool allowlist.
- **Security/PKI Agent** — generate local CA + server/client certs; document rotation and wiring of mTLS in Python `grpc.aio`.
- **DF Server Engineer** — implement AsyncIO gRPC server, 5 ms delay injection, Dockerfile, `.env`, cert loading.
- **SMFT Load Engineer** — implement `01_steady_client.py` and `02_coldconn_client.py`, pure‑async RPS control, JSONL outputs, Dockerfile, `.env`.
- **DevOps Agent** — add build‑time proto stub generation; keep runtime slim; provide exact `docker build`/`docker run` commands; optional `docker-compose.yaml`.
- **QA/Perf Analyst** — stdlib‑only post‑processor (e.g., `tools/summarize.py`) to compute percentiles, throughput, error rate; produce a short Markdown report.
- **Docs Agent** — finalize `README.md` with quickstart, env var tables, and result format specification.

---

## Notes on best practices

- Keep `CLAUDE.md` concise and evolve it as friction appears.
- Reuse a single channel for steady‑state to avoid handshake overhead; measure handshake cost separately in cold‑connection test.
- Prefer app‑level delay injection for determinism; document any optional netem usage explicitly.

- keep 50ms timeout
- Configuration:

  - 40ms: Server processing delay (as required)
  - 10ms: gRPC overhead budget (target)
  - 50ms: Total timeout (strict requirement)