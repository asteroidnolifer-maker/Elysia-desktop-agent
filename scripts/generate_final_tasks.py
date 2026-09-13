#!/usr/bin/env python3
"""Add massive bulk tasks - final push to ~1M."""
import sqlite3

DB = "/data/elysia/orchestrator/taskboard.sqlite"

# Final massive categories
FINAL = {
    "react_hooks": ["useLocalStorage", "useDebounce", "useThrottle", "useFetch", "useForm", "useModal", "useClipboard", "useGeolocation", "useMediaQuery", "useDarkMode", "useIntersection", "useScript", "useEventListener", "useWindowSize", "useOnlineStatus", "useHover", "useLongPress", "usePrevious", "useUpdateEffect", "useMount", "useUnmount", "useTimeout", "useInterval", "useAnimationFrame", "useRaf", "useQueue", "useStack", "useMap", "useSet", "useCounter", "useToggle", "useBoolean", "useMethods", "useReducer", "useStateLazy", "useimmer", "useRedux", "useContext", "useRef", "useMemo", "useCallback", "useLayoutEffect", "useDebugValue", "useId", "useTransition", "useDeferredValue", "useSyncExternalStore", "useInsertionEffect", "useImperativeHandle", "useForwardRef"],
    "python_utils": ["flatten_list", "chunk_list", "deduplicate", "rotate_list", "interleave", "partition", "group_by", "merge_dicts", "deep_get", "deep_set", "compact", "unique", "pluck", "pick", "omit", "map_keys", "map_values", "filter_dict", "sort_dict", "invert_dict", "flatten_dict", "nested_get", "nested_set", "safe_div", "clamp", "lerp", "remap", "format_bytes", "format_number", "slugify", "camelize", "snakeify", "humanize", "truncate", "wrap", "unwrap", "capitalize_words", "title_case", "pascal_case", "camel_case", "kebab_case", "snake_case", "dot_case", "path_case", "constant_case", "alternating_case", "inverse_case"],
    "go_patterns": ["worker_pool", "pipeline", "fan_out", "fan_in", "rate_limiter", "circuit_breaker", "retry", "timeout", "context_cancel", "err_group", "semaphore", "mutex", "rw_mutex", "atomic_counter", "channel_buffer", "select_statement", "range_channel", "goroutine_leak_detector", "memory_pool", "sync_pool", "sync_map", "sync_once", "sync_waitgroup", "sync_cond", "sync_fifo"],
    "rust_concepts": ["ownership", "borrowing", "lifetime", "trait_object", "enum_pattern", "pattern_matching", "error_handling", "option_result", "iterators", "closures", "smart_pointers", "rc_arc", "ref_cell", "cell_type", "box_type", "pin_type", "future_async", "tokio_runtime", "serde_derive", "macro_rules", "derive_clone", "derive_debug", "derive_partial_eq", "derive_hash", "derive_serialize"],
    "sql_queries": ["CTE recursive query", "window function rank", "pivot table query", "unpivot query", "lateral join", "full outer join", "self join", "cross join", "subquery optimization", "index hint", "query plan analysis", "batch insert", "upsert query", "merge statement", "conditional aggregation", "running total", "gap and islands", "sequential gaps", "nearest neighbor", "top N per group", "pct of total", "year over year", "month over month", "rolling average", "cumulative sum", "first last value", "lead lag", "ntile", "dense rank", "percent rank"],
    "regex_patterns": ["email validator", "phone validator", "URL validator", "IP address validator", "credit card validator", "SSN validator", "ZIP code validator", "date validator", "time validator", "hex color validator", "UUID validator", "base64 validator", "HTML tag parser", "CSS selector parser", "JSON extractor", "CSV parser", "markdown parser", "code block extractor", "comment stripper", "whitespace normalizer"],
    "git_operations": ["interactive rebase", "squash commits", "cherry-pick range", "bisect automation", "worktree management", "stash management", "reflog recovery", "submodule update", "subtree merge", "revert commit", "reset soft", "reset mixed", "reset hard", "clean untracked", "prune remote", "fetch pruned", "pull rebase", "push force with lease", "branch tracking", "tag management"],
    "docker_commands": ["build multi-stage", "compose up", "compose down", "volume create", "network create", "container inspect", "image prune", "system df", "exec interactive", "logs follow", "stats monitor", "cp container", "diff changes", "top processes", "port publish", "env set", "restart policy", "health check", "resource limits", "secret management"],
    "linux_commands": ["find files", "grep recursive", "sed replace", "awk processing", "xargs parallel", "tar compress", "rsync backup", "cron scheduling", "systemctl management", "journalctl logging", "netstat connections", "ss sockets", "top monitoring", "htop interactive", "df disk usage", "du directory", "free memory", "lscpu info", "lsblk devices", "mount filesystem"],
    "aws_services": ["Lambda function", "EC2 instance", "S3 bucket", "RDS database", "DynamoDB table", "SQS queue", "SNS topic", "CloudFront distribution", "API Gateway route", "ECS cluster", "EKS cluster", "Step Functions state machine", "EventBridge rule", "Kinesis stream", "Redshift cluster", "ElastiCache cluster", "IAM role policy", "VPC subnet group", "Security group rule", "CloudWatch alarm"],
    "gcp_services": ["Cloud Function", "Compute Engine", "Cloud Storage", "Cloud SQL", "Firestore", "Pub/Sub", "Cloud Run", "GKE cluster", "Cloud Build", "Cloud Deploy", "BigQuery dataset", "Cloud Composer", "Cloud Tasks", "Cloud Endpoints", "Cloud Armor", "Cloud CDN", "Cloud DNS", "Cloud NAT", "Cloud VPN", "Cloud Interconnect"],
    "azure_services": ["Azure Function", "Virtual Machine", "Blob Storage", "Azure SQL", "Cosmos DB", "Service Bus", "Event Grid", "AKS cluster", "Azure DevOps", "Azure Pipeline", "Azure Monitor", "Azure Sentinel", "Azure Front Door", "Azure Firewall", "Azure AD", "Key Vault", "Azure Redis", "Azure Search", "Azure Bot Service", "Azure Cognitive Services"],
    "kubernetes_resources": ["Deployment manifest", "Service definition", "ConfigMap", "Secret", "Ingress rule", "PersistentVolume", "PersistentVolumeClaim", "StatefulSet", "DaemonSet", "CronJob", "Job", "NetworkPolicy", "ResourceQuota", "LimitRange", "ServiceAccount", "Role binding", "ClusterRole", "PodDisruptionBudget", "HorizontalPodAutoscaler", "VerticalPodAutoscaler"],
    "terraform_resources": ["AWS VPC", "AWS Subnet", "AWS Security Group", "AWS EC2 Instance", "AWS RDS Instance", "AWS S3 Bucket", "AWS Lambda Function", "AWS IAM Role", "AWS CloudWatch Alarm", "AWS SNS Topic", "GCP VPC Network", "GCP Compute Instance", "GCP Cloud Storage", "GCP Cloud Function", "GCP SQL Database", "Azure VNet", "Azure VM", "Azure Storage Account", "Azure Function App", "Azure SQL Database"],
    "github_actions": ["Build and test", "Deploy to staging", "Deploy to production", "Run linter", "Run type checker", "Run unit tests", "Run integration tests", "Run E2E tests", "Build Docker image", "Push to registry", "Scan for vulnerabilities", "Generate documentation", "Release please", "Dependabot auto-merge", "Cache dependencies", "Matrix build", "Secret scanning", "CodeQL analysis", "Performance testing", "Smoke testing"],
    "ci_cd_pipelines": ["GitHub Actions workflow", "GitLab CI pipeline", "Jenkins pipeline", "CircleCI config", "Travis CI config", "Azure DevOps pipeline", "AWS CodePipeline", "Bitbucket pipeline", "Drone CI pipeline", "Buildkite pipeline", "TeamCity configuration", "Bamboo plan", "GoCD pipeline", "ArgoCD application", "Flux CD deployment", "Tekton pipeline", "Concourse pipeline", "Woodpecker CI", "Woodpecker pipeline", "Dagger pipeline"],
    "monitoring_metrics": ["CPU utilization", "Memory usage", "Disk I/O", "Network throughput", "Request latency", "Error rate", "Throughput", "Saturation", "Availability", "SLA compliance", "SLO adherence", "Error budget burn", "P99 latency", "P95 latency", "P50 latency", "Request count", "Response size", "Queue depth", "Connection pool", "Thread count"],
    "logging_patterns": ["Structured logging", "Correlation IDs", "Request tracing", "Error aggregation", "Log sampling", "Log rotation", "Log shipping", "Log parsing", "Log alerting", "Log retention", "Log archival", "Log compression", "Log encryption", "Log access control", "Log audit", "Log compliance", "Log analysis", "Log visualization", "Log search", "Log dashboard"],
    "security_headers": ["Content-Security-Policy", "Strict-Transport-Security", "X-Content-Type-Options", "X-Frame-Options", "X-XSS-Protection", "Referrer-Policy", "Permissions-Policy", "Cross-Origin-Opener-Policy", "Cross-Origin-Resource-Policy", "Cross-Origin-Embedder-Policy", "X-Permitted-Cross-Domain-Policies", "X-Download-Options", "X-DNS-Prefetch-Control", "Expect-CT", "Public-Key-Pins"],
    "oauth_flows": ["Authorization Code", "Authorization Code PKCE", "Client Credentials", "Device Code", "Implicit", "Resource Owner Password", "JWT Bearer", "SAML 2.0", "OpenID Connect", "OAuth2 to OAuth1", "Token Exchange", "Token Revocation", "Token Introspection", "Dynamic Client Registration", "Discovery Document", "Well-Known Endpoint"],
}

def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT MAX(id) FROM tasks")
    task_id = c.fetchone()[0] + 1

    total = 0
    for cat, templates in FINAL.items():
        for i in range(2000):
            base = templates[i % len(templates)]
            suffix = f" #{i // len(templates) + 1}" if i >= len(templates) else ""
            title = f"{base}{suffix}"
            files = f'["{cat}_{i+1}"]'
            c.execute(
                "INSERT INTO tasks (id, title, description, files, status, priority, created_at) VALUES (?, ?, ?, ?, 'open', 5, datetime('now'))",
                (task_id, title, title, files)
            )
            task_id += 1
            total += 1

    conn.commit()
    c.execute("SELECT COUNT(*) FROM tasks")
    final = c.fetchone()[0]
    conn.close()
    print(f"[+] Added {total} tasks, {final} total in database")

if __name__ == "__main__":
    main()
