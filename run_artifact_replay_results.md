# Run Artifact Direct Replay Results

This note records experiments where the final testcase artifacts under `runs/` were converted into real packets and replayed in the remote P4 environments. Unlike the earlier bug-trigger document, the traffic here was not reconstructed manually from intent; it was sent from the generated `packet_sequence` in the testcase JSON files.

## Method
- Sender script:
  - `scripts/testcase_packet_sender.py`
- Remote host:
  - `root@172.22.231.15`
- Replay principle:
  - Use the generated testcase JSON from `runs/..._testcases/*.json`.
  - Convert each `packet_sequence` item into a real Ethernet/IP/TCP or custom probe packet.
  - Execute required operator actions when needed.
  - Observe actual delivery by remote `tcpdump` or switch pcaps.

## 1. Stateful Firewall
- Testcases:
  - `runs/2026-03-07T064109Z_testcases/positive_internal_initiates.json`
  - `runs/2026-03-07T064109Z_testcases/negative_external_initiates.json`
- Remote programs:
  - Correct: `/home/gsj/P4/tutorials/exercises/firewall_correct`
  - Buggy: `/home/gsj/P4/tutorials/exercises/firewall_bug_block_replies`
- Replay details:
  - Packet 1: replayed from `h1` as generated SYN.
  - Packet 2: replayed from `h3` as generated SYN-ACK.
  - Packet 3: replayed from `h3` as generated external SYN.
- Observed result in correct version:
  - Packet 1 appeared in `s1-eth1_in.pcap`, `s1-eth3_out.pcap`, `s2-eth4_in.pcap`, and `s2-eth1_out.pcap`.
  - Packet 2 appeared in `s2-eth1_in.pcap`, `s2-eth4_out.pcap`, `s1-eth3_in.pcap`, and `s1-eth1_out.pcap`.
  - Packet 3 appeared in `s2-eth1_in.pcap`, `s2-eth4_out.pcap`, and `s1-eth3_in.pcap`, but did not appear in `s1-eth1_out.pcap`.
- Interpretation:
  - The replayed positive testcase matched the oracle: internal SYN and external SYN-ACK were both delivered.
  - The replayed negative testcase matched the oracle: external-initiated SYN was dropped before reaching `h1`.
- Observed result in buggy version:
  - Packet 1 still reached the network normally.
  - Packet 2 appeared up to `s1-eth3_in.pcap` but did not appear in `s1-eth1_out.pcap`.
- Interpretation:
  - The same run artifact exposed the reply-blocking firewall bug directly.

## 2. Heavy Hitter Detector
- Testcase:
  - `runs/2026-03-07T041513Z_testcases/positive_heavy_hitter_triggered.json`
- Remote program:
  - `/home/gsj/P4/bug_experiments/heavy_hitter_threshold10`
- Precondition:
  - This testcase contains `manual_threshold_override -> 10` in `execution_sequence`.
  - The replay therefore used the threshold-10 environment that matches the testcase assumption.
- Replay details:
  - All 15 generated packets were replayed from `h1` using the testcase JSON.
  - Actual reception was observed on `h2` by `tcpdump` with the testcase 5-tuple filter.
- Observed result:
  - `10` packets were captured at `h2`.
- Interpretation:
  - This matches the oracle encoded in the testcase: the generated run artifact really triggers the heavy-hitter threshold behavior when replayed as real packets.

## 3. Fast Reroute
- Testcase:
  - `runs/2026-03-07T051823Z_testcases/fast_reroute_after_link_failure.json`
- Remote programs:
  - Correct: `/home/gsj/P4/bug_experiments/fast_reroute_correct`
  - Buggy: `/home/gsj/P4/bug_experiments/fast_reroute_no_local_failover`
- Replay details:
  - Topology started with `p4run --config p4app.json`.
  - Controller state installed through `controller.py` initialization.
  - The testcase operator action `manual_link_event` was executed by failing link `s1-s2` and updating the `linkState` registers.
  - The 10 generated packets in `fast_reroute_after_link_failure.json` were replayed from `h2`.
  - Actual reception was observed on `h4` by `tcpdump`.
- Observed result in correct version:
  - `10` packets were captured at `h4`.
- Observed result in buggy version:
  - `0` packets were captured at `h4`.
- Interpretation:
  - The run artifact directly reproduces the intended failover scenario.
  - The same generated packets plus testcase operator action distinguish the correct fast-reroute implementation from the no-local-failover bug.

## 4. Link Monitor
- Testcase:
  - `runs/2026-03-07T070712Z_testcases/positive_link_utilization_monitoring.json`
- Remote programs:
  - Correct: `/home/gsj/P4/tutorials/exercises/link_monitor_correct`
  - Buggy: `/home/gsj/P4/tutorials/exercises/link_monitor_zero_bytecnt`
- Replay details:
  - All generated packets were replayed from `h1` using the testcase JSON: 20 IPv4 traffic packets followed by 1 probe packet.
  - Observation was taken from switch pcaps rather than terminal prints, because this gives a cleaner packet-level record.
- Observed result in correct version:
  - `s1-eth1_out.pcap` contained returned probe packets with EtherType `0x0812`.
  - The returned probe payload encoded a non-zero `byte_cnt` field. From the packet bytes:
    - `... 81 01 00 00 00 10 ...`
    - i.e. `byte_cnt = 0x00000010`.
- Observed result in buggy version:
  - `s1-eth1_out.pcap` also contained returned probe packets with EtherType `0x0812`.
  - The corresponding probe payload encoded zero byte count:
    - `... 81 01 00 00 00 00 ...`
    - i.e. `byte_cnt = 0x00000000`.
- Interpretation:
  - The run artifact is directly replayable and does distinguish the correct implementation from the zero-byte-count bug.
  - However, this replay also exposes a testcase-specification weakness: the generated probe packet only contains `probe_fwd.egress_spec = 1`, so in practice it loops back on `s1` instead of reaching `h3` as written in the oracle. Therefore, the artifact is executable and bug-revealing, but its probe-path semantics are still under-specified.

## 5. Congestion-Aware Load Balancing
- Testcase:
  - `runs/2026-03-07T063623Z_testcases/congestion_reroute.json`
- Remote program:
  - Correct: `/home/gsj/P4/bug_experiments/calb_correct`
- Replay details:
  - The testcase operator action `extra_high_rate_flows` was instantiated as concurrent background TCP `iperf3` flows on the medium topology.
  - The 5 generated testcase packets were then replayed from `h1` to `h5`.
  - Actual reception was observed on `h5` by `tcpdump`.
- Observed result:
  - All 5 generated packets were captured at `h5`.
  - Even after a stronger congestion instantiation, no stable `feedback` packets with EtherType `0x7778` were observed in the correct-version pcaps during this direct replay run.
- Interpretation:
  - The CALB run artifact is directly replayable as real traffic: the 5 generated packets can be materialized and delivered in the target environment.
  - However, the current testcase encodes the congestion-inducing step only abstractly (`extra_high_rate_flows on primary_path`). In programmatic replay, this abstraction is not yet specific enough to stably demonstrate the oracle claim about congestion-triggered reroute or feedback generation.
  - In other words, the artifact is executable, but the operator-action portion of the testcase is still too weakly grounded for a deterministic end-to-end replay verdict on reroute behavior.

## Overall Conclusion
- Fully successful direct replay with semantic confirmation:
  - `Stateful_Firewall`
  - `Heavy_Hitter_Detector`
  - `Fast_Reroute`
- Direct replay successful, but testcase semantics need refinement:
  - `Link_Monitor`
  - `Congestion_Aware_Load_Balancing`

This means the system has already crossed the important engineering threshold: its `runs/` outputs are no longer just inspection artifacts, but can be transformed into real packets and used to drive real remote P4 executions. The remaining gap is not basic executability, but the precision with which some higher-level observation and operator-action semantics are encoded in the generated testcases.
