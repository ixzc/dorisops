Built-in playbooks ship in `src/dorisops/playbooks/`.

| id | modes |
|----|-------|
| `be-node-down` | integrated, cloud |
| `memory-pressure` | integrated, cloud |
| `fe-node-down` | integrated, cloud |
| `too-many-versions` | integrated, cloud (clone/tablet health is integrated-only) |
| `query-timeout` | integrated, cloud |
| `metaservice-down` | cloud only |

Do not commit customer runbooks, CIR ids, warehouse ids, or jumphost names.
Load a private pack with `--playbook-dir`.
