"""Persistência da Hana organizada pelo papel de cada memória.

Contrato da pasta:
- short_term/ : conversa recente por canal e histórico do painel;
- fixed/      : regras permanentes que entram sempre no prompt;
- long_term/  : fatos, RAG, embeddings, extração, manutenção e sono;
- events/     : observabilidade e projeções do Terminal;
- core.py     : coordena curta/fixa, configurações, skills e prompt;
- store.py    : fachada pública que coordena eventos e memória longa;
- storage.py  : persistência específica do Agent Core;
- sqlite.py   : conexão SQLite compartilhada.

Contrato preservado: projeções visuais com `conversation=false`, chat_log e
settings não entram na conversa canônica. Nenhum módulo desta pasta altera ou
limpa histórico automaticamente durante importação.
"""
