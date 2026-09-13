from hypothesis import given, strategies as st, settings, HealthCheck


def calculate_savepoints_to_delete(all_sp: list[str], max_retained: int) -> list[str]:
    if max_retained < 0:
        raise ValueError("max_retained must be >= 0")
    if len(all_sp) <= max_retained:
        return []
    return list(all_sp[: len(all_sp) - max_retained])


def parse_kafka_lag_output(stdout: str) -> int:
    """Exact parsing logic used in orchestrator.py line 220-225."""
    total_lag = 0
    for line in stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) > 5 and parts[5].isdigit():
            total_lag += int(parts[5])
    return total_lag


@given(
    n=st.integers(min_value=0, max_value=50),
    k=st.integers(min_value=1, max_value=20),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_savepoint_rotation_invariant(n: int, k: int) -> None:
    all_sp = [f"savepoint-{i}" for i in range(1, n + 1)]
    to_delete = calculate_savepoints_to_delete(all_sp, k)

    if n <= k:
        assert to_delete == []
    else:
        assert len(to_delete) == n - k

    retained = [sp for sp in all_sp if sp not in set(to_delete)]
    assert len(retained) == min(n, k)

    if n > k:
        assert retained == all_sp[n - k :]
        assert to_delete == all_sp[: n - k]


_TOPICS = st.sampled_from(["positions.v1", "static.v1", "telemetry"])
_GROUPS = st.sampled_from(["flink-ais-consumer-prod-v1", "consumer-group-1"])
_IDS = st.text(alphabet="abcdefghijklmnop0123456789-", min_size=1, max_size=12)
_HOSTS = st.sampled_from(["/10.0.0.1", "/10.0.0.2", "host-1", "host-2"])


@st.composite
def _kafka_output(draw):
    n_lines = draw(st.integers(min_value=0, max_value=25))
    lines = []
    expected_total = 0

    header_variants = [
        "GROUP           TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID     HOST            CLIENT-ID",
        "Consumer group 'x' has no active members.",
        "",
        "   ",
        "Some random non-tabular log line",
    ]
    n_headers = draw(st.integers(min_value=0, max_value=3))
    for _ in range(n_headers):
        lines.append(draw(st.sampled_from(header_variants)))

    for _ in range(n_lines):
        group = draw(_GROUPS)
        topic = draw(_TOPICS)
        partition = draw(st.integers(min_value=0, max_value=16))
        current = draw(st.integers(min_value=0, max_value=10_000_000))
        lag = draw(st.integers(min_value=0, max_value=50_000))
        end = current + lag
        consumer = draw(_IDS)
        host = draw(_HOSTS)
        client = draw(_IDS)
        line = (
            f"{group}   {topic}   {partition}   {current}   {end}   {lag}   "
            f"{consumer}   {host}   {client}"
        )
        lines.append(line)
        expected_total += lag

    draw(st.randoms()).shuffle(lines)
    return "\n".join(lines), expected_total


@given(_kafka_output())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_kafka_lag_parser_sum_invariant(payload) -> None:
    stdout, expected_total = payload
    result = parse_kafka_lag_output(stdout)
    assert result == expected_total
    assert result >= 0


@given(st.text())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_kafka_lag_parser_never_negative(s: str) -> None:
    assert parse_kafka_lag_output(s) >= 0
