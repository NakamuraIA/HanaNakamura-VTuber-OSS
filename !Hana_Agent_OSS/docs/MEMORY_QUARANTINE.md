# Memory Quarantine

The old Hana memory and previous vector data are no longer part of the active
runtime.

The current rule is:

- do not read legacy memory during normal Agent OSS execution;
- do not migrate old conversations into the new store;
- leave old local files only as quarantine if they still exist on disk;
- use the new SQLite/FTS/JSONL memory in `runtime/`.

This reset is intentional. Hana Agent OSS starts with a clean memory system and
keeps latency predictable before future provider-backed planners and MCP tools
are connected.
