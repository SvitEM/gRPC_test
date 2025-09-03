#!/usr/bin/env python3
"""
Post-processing tool for gRPC latency test results
Computes percentiles, throughput, and error rates using only stdlib
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Any
import statistics


def load_results(file_path: Path) -> tuple[str, List[Dict[str, Any]]]:
    """Load JSONL results file and extract test name and data"""
    if not file_path.exists():
        raise FileNotFoundError(f"Results file not found: {file_path}")
    
    results = []
    test_name = None
    
    with open(file_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
                
            # First line should be test header
            if line_num == 1:
                if line.startswith('#TEST='):
                    test_name = line.split('=', 1)[1]
                    continue
                else:
                    raise ValueError(f"Expected test header on line 1, got: {line}")
            
            # Parse JSON result
            try:
                result = json.loads(line)
                results.append(result)
            except json.JSONDecodeError as e:
                print(f"Warning: Invalid JSON on line {line_num}: {e}")
                continue
    
    if test_name is None:
        raise ValueError("Test name header not found")
    
    return test_name, results


def compute_percentiles(values: List[float], percentiles: List[float]) -> Dict[str, float]:
    """Compute specified percentiles from a list of values"""
    if not values:
        result: Dict[str, float] = {}
        for p in percentiles:
            key = _percentile_key(p)
            result[key] = 0.0
        return result
    
    sorted_values = sorted(values)
    result = {}
    
    for p in percentiles:
        key = _percentile_key(p)
        if p == 1.0:
            result[key] = sorted_values[-1]  # max
        else:
            idx = p * (len(sorted_values) - 1)
            lower_idx = int(idx)
            upper_idx = min(lower_idx + 1, len(sorted_values) - 1)
            
            if lower_idx == upper_idx:
                result[key] = sorted_values[lower_idx]
            else:
                # Linear interpolation
                weight = idx - lower_idx
                result[key] = (
                    sorted_values[lower_idx] * (1 - weight) +
                    sorted_values[upper_idx] * weight
                )
    
    return result


def _percentile_key(p: float) -> str:
    """Return a stable key name for a percentile value.
    - 1.0 -> 'p100'
    - 0.999 -> 'p999' (P99.9)
    - Others use two-digit percent: e.g., 0.95 -> 'p95'
    """
    if p >= 1.0:
        return "p100"
    if abs(p - 0.999) < 1e-9:
        return "p999"
    return f"p{int(round(p * 100))}"


def analyze_steady_results(test_name: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze 01_steady test results"""
    total_requests = len(results)
    successful_requests = [r for r in results if r.get("ok", False)]
    failed_requests = [r for r in results if not r.get("ok", False)]
    
    # Extract latencies from successful requests
    latencies = []
    for r in successful_requests:
        if "net_latency_ms" in r:
            latencies.append(r["net_latency_ms"])
        elif "latency_ms" in r:
            latencies.append(r["latency_ms"])
    
    # Compute percentiles
    percentiles = [0.5, 0.9, 0.95, 0.99, 0.999, 1.0]
    latency_stats = compute_percentiles(latencies, percentiles)
    
    # Error breakdown
    error_codes = {}
    for r in failed_requests:
        code = r.get("code", r.get("error", "unknown"))
        error_codes[code] = error_codes.get(code, 0) + 1
    
    return {
        "test_name": test_name,
        "total_requests": total_requests,
        "successful_requests": len(successful_requests),
        "failed_requests": len(failed_requests),
        "success_rate": len(successful_requests) / total_requests if total_requests > 0 else 0.0,
        "latency_stats": latency_stats,
        "mean_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "error_breakdown": error_codes
    }


def analyze_coldconn_results(test_name: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze 02_coldconn test results"""
    total_attempts = len(results)
    successful_attempts = [r for r in results if r.get("ok", False)]
    failed_attempts = [r for r in results if not r.get("ok", False)]
    
    # Extract timing data from successful attempts
    connect_times = [r["t_connect_ms"] for r in successful_attempts if "t_connect_ms" in r]
    first_rpc_times = [r["t_first_rpc_ms"] for r in successful_attempts if "t_first_rpc_ms" in r]
    total_times = [r["t_total_ms"] for r in successful_attempts if "t_total_ms" in r]
    
    # Compute percentiles for each timing metric
    percentiles = [0.5, 0.9, 0.95, 0.99, 0.999, 1.0]
    
    connect_stats = compute_percentiles(connect_times, percentiles)
    first_rpc_stats = compute_percentiles(first_rpc_times, percentiles)
    total_stats = compute_percentiles(total_times, percentiles)
    
    # Error breakdown
    error_codes = {}
    for r in failed_attempts:
        code = r.get("code", r.get("error", "unknown"))
        error_codes[code] = error_codes.get(code, 0) + 1
    
    return {
        "test_name": test_name,
        "total_attempts": total_attempts,
        "successful_attempts": len(successful_attempts),
        "failed_attempts": len(failed_attempts),
        "success_rate": len(successful_attempts) / total_attempts if total_attempts > 0 else 0.0,
        "connect_time_stats": connect_stats,
        "first_rpc_time_stats": first_rpc_stats,
        "total_time_stats": total_stats,
        "mean_connect_time_ms": statistics.mean(connect_times) if connect_times else 0.0,
        "mean_first_rpc_time_ms": statistics.mean(first_rpc_times) if first_rpc_times else 0.0,
        "mean_total_time_ms": statistics.mean(total_times) if total_times else 0.0,
        "error_breakdown": error_codes
    }


def format_steady_report(analysis: Dict[str, Any]) -> str:
    """Format steady test results as markdown report"""
    report = f"""# {analysis['test_name']} Results

## Summary
- **Total Requests**: {analysis['total_requests']:,}
- **Successful**: {analysis['successful_requests']:,} ({analysis['success_rate']:.1%})
- **Failed**: {analysis['failed_requests']:,}

## Latency Statistics (ms)
- **Mean**: {analysis['mean_latency_ms']:.2f}
- **P50**: {analysis['latency_stats']['p50']:.2f}
- **P90**: {analysis['latency_stats']['p90']:.2f}
- **P95**: {analysis['latency_stats']['p95']:.2f}
- **P99**: {analysis['latency_stats']['p99']:.2f}
- **P99.9**: {analysis['latency_stats']['p999']:.2f}
- **Max**: {analysis['latency_stats']['p100']:.2f}

"""
    
    if analysis['error_breakdown']:
        report += "## Error Breakdown\n"
        for code, count in analysis['error_breakdown'].items():
            rate = count / analysis['total_requests']
            report += f"- **{code}**: {count:,} ({rate:.1%})\n"
        report += "\n"
    
    return report


def format_coldconn_report(analysis: Dict[str, Any]) -> str:
    """Format cold connection test results as markdown report"""
    report = f"""# {analysis['test_name']} Results

## Summary
- **Total Attempts**: {analysis['total_attempts']:,}
- **Successful**: {analysis['successful_attempts']:,} ({analysis['success_rate']:.1%})
- **Failed**: {analysis['failed_attempts']:,}

## Connection Time Statistics (ms)
- **Mean**: {analysis['mean_connect_time_ms']:.2f}
- **P50**: {analysis['connect_time_stats']['p50']:.2f}
- **P90**: {analysis['connect_time_stats']['p90']:.2f}
- **P95**: {analysis['connect_time_stats']['p95']:.2f}
- **P99**: {analysis['connect_time_stats']['p99']:.2f}
- **P99.9**: {analysis['connect_time_stats']['p999']:.2f}
- **Max**: {analysis['connect_time_stats']['p100']:.2f}

## First RPC Time Statistics (ms)
- **Mean**: {analysis['mean_first_rpc_time_ms']:.2f}
- **P50**: {analysis['first_rpc_time_stats']['p50']:.2f}
- **P90**: {analysis['first_rpc_time_stats']['p90']:.2f}
- **P95**: {analysis['first_rpc_time_stats']['p95']:.2f}
- **P99**: {analysis['first_rpc_time_stats']['p99']:.2f}
- **P99.9**: {analysis['first_rpc_time_stats']['p999']:.2f}
- **Max**: {analysis['first_rpc_time_stats']['p100']:.2f}

## Total Time Statistics (ms)
- **Mean**: {analysis['mean_total_time_ms']:.2f}
- **P50**: {analysis['total_time_stats']['p50']:.2f}
- **P90**: {analysis['total_time_stats']['p90']:.2f}
- **P95**: {analysis['total_time_stats']['p95']:.2f}
- **P99**: {analysis['total_time_stats']['p99']:.2f}
- **P99.9**: {analysis['total_time_stats']['p999']:.2f}
- **Max**: {analysis['total_time_stats']['p100']:.2f}

"""
    
    if analysis['error_breakdown']:
        report += "## Error Breakdown\n"
        for code, count in analysis['error_breakdown'].items():
            rate = count / analysis['total_attempts']
            report += f"- **{code}**: {count:,} ({rate:.1%})\n"
        report += "\n"
    
    return report


def main():
    """Main entry point"""
    if len(sys.argv) != 2:
        print("Usage: python summarize.py <results_file.txt>")
        sys.exit(1)
    
    results_file = Path(sys.argv[1])
    
    try:
        # Load and parse results
        test_name, results = load_results(results_file)
        
        if not results:
            print(f"No results found in {results_file}")
            sys.exit(1)
        
        # Analyze based on test type
        if test_name == "01_steady":
            analysis = analyze_steady_results(test_name, results)
            report = format_steady_report(analysis)
        elif test_name == "02_coldconn":
            analysis = analyze_coldconn_results(test_name, results)
            report = format_coldconn_report(analysis)
        else:
            print(f"Unknown test type: {test_name}")
            sys.exit(1)
        
        # Write report
        report_file = results_file.with_suffix('.md')
        with open(report_file, 'w') as f:
            f.write(report)
        
        print(f"Analysis complete. Report written to: {report_file}")
        
        # Also print summary to stdout
        print("\n" + "="*60)
        print(report)
        
    except Exception as e:
        print(f"Error processing results: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
