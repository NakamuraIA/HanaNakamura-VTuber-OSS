# Module Contract

Every module must declare a manifest and expose structured tools.

## Manifest

```json
{
  "id": "file.module",
  "name": "File Module",
  "type": "module",
  "version": "0.1.0",
  "capabilities": ["file.read", "file.write"],
  "entrypoint": {
    "kind": "python",
    "module": "hana_agent_oss.modules.file"
  },
  "permissions": {
    "risk": "medium",
    "requires_user_enable": false
  }
}
```

## Tool Result

```json
{
  "ok": true,
  "tool": "file.write",
  "output": {
    "path": "C:\\Users\\Example\\Desktop\\Hana.txt",
    "bytes": 1024
  },
  "error": null,
  "artifacts": ["C:\\Users\\Example\\Desktop\\Hana.txt"]
}
```

Tools return observations to the Agent Core. The final user answer is composed
after verification.

