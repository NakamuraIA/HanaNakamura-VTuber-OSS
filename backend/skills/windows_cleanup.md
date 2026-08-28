# Skill: Windows Cleanup

Limpeza profunda no Windows — temp, caches, logs, lixeira, browser caches, e opções agressivas (shadow copies, SysMain, WinSxS).

## Script

`E:\Projeto_Hana_AI\data\scripts\windows_cleanup.py`

## Uso

### Limpeza padrão (segura)

```
python data/scripts/windows_cleanup.py
```

### Dry-run (simular antes)

```
python data/scripts/windows_cleanup.py --dry-run
```

### Limpeza agressiva (requer Admin)

```
python data/scripts/windows_cleanup.py --aggressive
```

### Agressiva + dry-run

```
python data/scripts/windows_cleanup.py --aggressive --dry-run
```

## O que limpa (modo padrão)

- [x] Pastas TEMP (usuário e sistema)
- [x] Prefetch (.pf)
- [x] Lixeira ($Recycle.bin)
- [x] Cache do Chrome, Edge, Firefox, Brave
- [x] Cache do Windows Update (SoftwareDistribution\Download)
- [x] Arquivos .log (Windows Logs, TEMP)
- [x] Cache .NET Native
- [x] Lista de arquivos recentes do Explorer
- [x] Thumbnail cache
- [x] Cache DNS (`ipconfig /flushdns`)
- [x] CleanMgr (limpeza de disco)

## O que limpa (modo agressivo — `--aggressive`)

- [x] Shadow Copies (pontos de restauração) — requer Admin
- [x] Desabilita SysMain (Superfetch) — requer Admin
- [x] WinSxS (DISM StartComponentCleanup) — requer Admin

## Requisitos

- Python 3.x
- Modo agressivo exige execução **como Administrador**
- Dry-run não precisa de Admin

## Observações

- A limpeza é segura para o uso diário no modo padrão.
- Shadow copies removem **todos** os pontos de restauração — útil pra liberar GB, mas sem volta.
- SysMain desabilitado não vai mais "otimizar" inicialização de apps — útil em SSDs.
- Se um arquivo estiver em uso, o script avisa e pula.