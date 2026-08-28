"""Rotas e serviços HTTP/WebSocket da Hana (FastAPI).

Estado atual:
- routers/  : um arquivo por domínio de rota; traduz HTTP <-> serviço. Alguns
  routers antigos ainda concentram orquestração que será extraída por etapas.
  `routers/validation.py` é uma ferramenta interna temporária da migração e
  deverá ser removida antes da publicação.
- services/ : concentra a maior parte da regra de negócio usada pelas rotas e
  conversa com core/, catalog/, memory/ e providers/.
- server.py : monta o app, CORS e ciclo de vida; ponto único de registro.

Destino: validação de entrada e formato de resposta ficam nos routers; regra de
negócio fica nos serviços. Frontend e backend se comunicam somente por
HTTP/WebSocket e devem continuar publicáveis separadamente.
"""
