# Remote Bug Trigger Experiments

## Environment
- Remote host: `root@172.22.231.15`
- Original P4 roots:
  - `/home/gsj/P4/tutorials/exercises/*`
  - `/home/gsj/P4/p4-learning/exercises/*`
- Bug-copy root:
  - `/home/gsj/P4/bug_experiments`
- Principle:
  - Never modify original programs.
  - Create a separate buggy copy per program.
  - Run the same trigger traffic against the original and buggy versions.

## 1. Heavy_Hitter_Detector
- Original directory:
  - `/home/gsj/P4/p4-learning/exercises/06-Heavy_Hitter_Detector/solution`
- Buggy directory:
  - `/home/gsj/P4/bug_experiments/heavy_hitter_threshold10`
- Injected bug:
  - `PACKET_THRESHOLD` changed from `1000` to `10`.
- Trigger traffic:
  - Send 20 packets from `h1` to `h2` using the provided `send.py`.
  - Run `receive.py` on `h2` to count arrivals.
- Observed result:
  - Correct version received `19` packets.
  - Buggy version received `10` packets.
- Conclusion:
  - The generated heavy-hitter seed successfully distinguishes the correct implementation from the threshold-bug implementation and triggers premature dropping behavior.

## 2. Link_Monitor
- Correct directory:
  - `/home/gsj/P4/tutorials/exercises/link_monitor_correct`
- Buggy directory:
  - `/home/gsj/P4/tutorials/exercises/link_monitor_zero_bytecnt`
- Injected bug:
  - `hdr.probe_data[0].byte_cnt = byte_cnt;` changed to `hdr.probe_data[0].byte_cnt = 0;`
- Trigger traffic:
  - Run `receive.py` and `send.py` on `h1`.
  - Run `iperf h1 h4` to create measurable traffic.
  - Compare printed `Mbps` values from probe results.
- Observed result:
  - Correct version reported repeated non-zero link utilizations, e.g. `0.0012986310264596073 Mbps`, `0.0011596174808469846 Mbps`, `3.1270813859706723 Mbps`.
  - Buggy version reported repeated `0.0 Mbps` on all observed links.
- Conclusion:
  - The telemetry-oriented seed successfully distinguishes the correct implementation from the bugged implementation where probe results no longer carry byte-count information.

## 3. Stateful_Firewall
- Correct directory:
  - `/home/gsj/P4/tutorials/exercises/firewall_correct`
- Buggy directory:
  - `/home/gsj/P4/tutorials/exercises/firewall_bug_block_replies`
- Injected bug:
  - In the external-to-internal validation branch, the reply-allow condition was inverted.
  - Correct code: `if (reg_val_one != 1 || reg_val_two != 1) { drop(); }`
  - Buggy code: `if (reg_val_one == 1 && reg_val_two == 1) { drop(); }`
- Trigger traffic:
  - Use the reference solution as the active `firewall.p4` in the correct copy.
  - Run `make run` and trigger `iperf h1 h3`.
  - Compare the internal-initiated TCP connection result between correct and buggy versions.
- Observed result:
  - Correct version: `iperf h1 h3` completed successfully with `2.6 Mbits/sec` and `3.0 Mbits/sec`.
  - Buggy version: `iperf h1 h3` failed to complete normally and did not print a successful bandwidth result.
  - Switch log evidence from the buggy version shows the reply packet matched an established bloom-filter state, but was still dropped:
    - `Read register 'MyIngress.bloom_filter_1' ... read value 1`
    - `Read register 'MyIngress.bloom_filter_2' ... read value 1`
    - Condition `reg_val_one == 1 && reg_val_two == 1` evaluated true.
    - `mark_to_drop(standard_metadata)` executed and the packet was dropped at ingress.
- Conclusion:
  - The generated stateful-firewall seed successfully triggers a reply-blocking bug that breaks the intended internal-initiated communication behavior.

## 4. Fast_Reroute
- Correct directory:
  - `/home/gsj/P4/bug_experiments/fast_reroute_correct`
- Buggy directory:
  - `/home/gsj/P4/bug_experiments/fast_reroute_no_local_failover`
- Injected bug:
  - Disable local fast reroute by preventing the switch from switching to `alternativeNH` when a failed primary link is detected.
  - Correct code: `if (meta.linkState > 0) { read_alternativePort(); }`
  - Buggy code: `if (meta.linkState > 1) { read_alternativePort(); }`
- Trigger traffic:
  - Start the topology with `p4run --config p4app.json`.
  - Let `controller.py` install primary and alternate next hops.
  - Run sustained `ping` traffic from `h2` to `h4`.
  - During the ping, bring down link `s1-s2` and update the `linkState` registers on both adjacent switches.
  - Compare packet loss during the failure window.
- Observed result:
  - Correct version: `40` packets transmitted, `39` received, `2.5%` packet loss.
  - Buggy version: `40` packets transmitted, `15` received, `62.5%` packet loss.
- Conclusion:
  - The generated fast-reroute seed successfully distinguishes the correct implementation from the no-failover bug: the correct version maintains connectivity after the local failure, while the buggy version loses most packets during the failure window.

## 5. Congestion_Aware_Load_Balancing
- Correct directory:
  - `/home/gsj/P4/bug_experiments/calb_correct`
- Buggy directory:
  - `/home/gsj/P4/bug_experiments/calb_no_feedback`
- Injected bug:
  - Raise the congestion-feedback trigger threshold so that feedback packets are effectively never generated.
  - Correct code: `if (hdr.telemetry.enq_qdepth > 50)`
  - Buggy code: `if (hdr.telemetry.enq_qdepth > 5000)`
- Trigger traffic:
  - Start the line topology with `p4run --config p4app-line.json`.
  - Generate 16 concurrent `iperf3` flows: 8 flows from `h1` to `h3` and 8 flows from `h2` to `h4`.
  - Use the generated pcaps to count `feedback` packets with EtherType `0x7778` and telemetry packets with EtherType `0x7777`.
- Observed result:
  - Correct version:
    - `pcap/s1-eth3_in.pcap` contained `6226` feedback packets and `19527` telemetry packets.
    - The same `6226` feedback packets were also visible on `pcap/s2-eth1_out.pcap`, `pcap/s2-eth2_in.pcap`, and `pcap/s3-eth3_out.pcap`, showing that congestion feedback was actively generated and propagated.
  - Buggy version:
    - `pcap/s1-eth3_in.pcap` contained `20214` telemetry packets but `0` feedback packets.
- Conclusion:
  - The generated CALB seed successfully triggers the congestion-feedback behavior in the correct implementation and cleanly exposes the threshold bug that suppresses all feedback generation.
