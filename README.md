# DorisOps

Read-only ops workbench for [Apache Doris](https://doris.apache.org/).

It is **not** an APM, **not** Grafana, and **not** a pager (PagerDuty / Flashduty).
It turns an alert or a `query_id` into a diagnosis case with commands you can run yourself.

Supports **integrated** (shared-nothing) and **cloud** (storage-compute separation) clusters.

## Status

Pre-alpha. This repository is the public shell (stage **S0**).

CLI case open, playbooks, local web UI, and MCP are not in this commit yet.

## Two lanes

| Lane | What you grant | What you get |
|------|----------------|--------------|
| **L0 diagnosis case** | Nothing (no FE/BE account) | Paste an alert → get a command pack and a decision tree. You run commands. You paste output back. |
| **L1 inspect** | Read-only FE MySQL + FE/BE HTTP | `SHOW FRONTENDS` / metrics / profile. If credentials are missing, DorisOps **downgrades to L0**. It does not invent cluster numbers. |

**P0–P1 are read-only.** The product may *describe* a stop-the-bleeding line from a playbook. It will not `SET`, `ALTER`, repair replicas, kill queries, or SSH.

## How you will use it (upcoming)

Local page (stage S4), after the CLI case flow exists:

```bash
dorisops web --bind 127.0.0.1:8787
```

Open the browser, paste an alert, copy commands, paste stdout back.

CLI (stages S1–S3), for scripts and CI:

```bash
dorisops case open --alert "be node down on host X" --mode integrated
```

Optional Cursor MCP (stage S7) calls the same case APIs.

Until those stages land, this repo only documents the contract.

## Cluster config

See [`examples/cluster.example.yaml`](examples/cluster.example.yaml).
Copy to `cluster.yaml` in a private location. That filename is gitignored.

- `mode: integrated` — shared-nothing FE/BE. No MetaService calls.
- `mode: cloud` — compute groups / MetaService. Local clone / disk rebalance playbooks do not apply.

## Playbooks

Built-in packs will be generic Apache Doris runbooks.

Private SOP directories (customer names, CIR, jumphosts) stay on your machine and are loaded with `--playbook-dir`. They are **not** part of this GitHub repository.

## License

Apache License 2.0. See [LICENSE](LICENSE).
