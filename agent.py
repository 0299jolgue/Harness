"""Bounded OpenAI tools loop, with a one-file delete confirmation gate."""
from __future__ import annotations
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from workspace import (list_files, read_file, write_file, edit_file, search_files,
                       create_folder, move_file, delete_file)

MAX_ROUNDS = 8
TOOLS = [
 {"type":"function","function":{"name":"list_files","description":"Lista ficheiros e pastas dentro de projetos/.","parameters":{"type":"object","properties":{"path":{"type":"string","default":"."}},"additionalProperties":False}}},
 {"type":"function","function":{"name":"read_file","description":"Lê um ficheiro de texto até 150 KB em projetos/.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"create_file","description":"Cria um novo ficheiro de texto em projetos/.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"write_file","description":"Cria ou substitui o conteúdo dum ficheiro de texto em projetos/.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"edit_file","description":"Substitui uma única ocorrência de texto dentro dum ficheiro.","parameters":{"type":"object","properties":{"path":{"type":"string"},"old_text":{"type":"string"},"new_text":{"type":"string"}},"required":["path","old_text","new_text"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"search_files","description":"Procura texto nos ficheiros de projetos/.","parameters":{"type":"object","properties":{"query":{"type":"string"},"path":{"type":"string","default":"."}},"required":["query"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"create_folder","description":"Cria uma pasta dentro de projetos/.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"move_file","description":"Move um ficheiro ou pasta dentro de projetos/.","parameters":{"type":"object","properties":{"source":{"type":"string"},"destination":{"type":"string"}},"required":["source","destination"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"delete_file","description":"Pede confirmação do utilizador antes de apagar um ficheiro em projetos/.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":False}}}
]

@dataclass
class Pending:
    req: Any
    messages: list[dict[str, Any]]
    tool_call: dict[str, Any]
    path: str

class PendingStore:
    def __init__(self): self.items: dict[str, Pending] = {}

def _run_tool(root: Path, name: str, args: dict):
    funcs = {"list_files":lambda:list_files(root, args.get("path", ".")),
      "read_file":lambda:read_file(root,args["path"]),
      "create_file":lambda:write_file(root,args["path"],args["content"],create_only=True),
      "write_file":lambda:write_file(root,args["path"],args["content"]),
      "edit_file":lambda:edit_file(root,args["path"],args["old_text"],args["new_text"]),
      "search_files":lambda:search_files(root,args["query"],args.get("path",".")),
      "create_folder":lambda:create_folder(root,args["path"]),
      "move_file":lambda:move_file(root,args["source"],args["destination"])}
    if name not in funcs: raise ValueError("Ferramenta desconhecida.")
    return funcs[name]()

async def _model(req, messages):
    base = req.base_url.strip().rstrip("/")
    if not (base.startswith("https://") or base.startswith("http://127.0.0.1")):
        raise HTTPException(400,"A Base URL tem de usar HTTPS (ou localhost).")
    body={"model":req.model,"messages":messages,"tools":TOOLS,"tool_choice":"auto","parallel_tool_calls":False,"temperature":req.temperature,"max_tokens":req.max_tokens}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300,connect=20),follow_redirects=False) as client:
            headers={}
            if req.api_key: headers["Authorization"]=f"Bearer {req.api_key}"
            response=await client.post(base+"/chat/completions",json=body,headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(502,f"Falha de ligação ao fornecedor ({type(exc).__name__}).") from None
    if response.status_code >= 400: raise HTTPException(502,"Fornecedor recusou o pedido Agent. Confirma modelo e suporte de ferramentas.")
    try:return response.json()
    except ValueError:raise HTTPException(502,"Resposta inválida do fornecedor.") from None

async def _continue(req, root:Path, store:PendingStore, messages, start_round=0):
    for _ in range(start_round, MAX_ROUNDS):
        result=await _model(req,messages)
        choices=result.get("choices") or []
        if not choices: raise HTTPException(502,"O fornecedor não devolveu escolhas.")
        msg=choices[0].get("message") or {}
        messages.append(msg)
        calls=msg.get("tool_calls") or []
        if not calls:
            return {"text":msg.get("content") or "Concluído.","messages":messages}
        for call in calls:
            fn=call.get("function") or {}; name=fn.get("name","")
            try: args=json.loads(fn.get("arguments") or "{}")
            except (TypeError,ValueError): args={}
            if name=="delete_file":
                try:
                    target=(root/args.get("path","")).resolve()
                    if target==root or root.resolve() not in target.parents or not target.is_file(): raise ValueError("Caminho não é um ficheiro dentro de projetos/.")
                    cid=secrets.token_urlsafe(18)
                    store.items[cid]=Pending(req,messages,call,args["path"])
                    return {"text":msg.get("content") or "", "messages":messages,
                            "confirmation":{"id":cid,"action":"delete_file","path":args["path"],"message":f"Apagar o ficheiro {args['path']}?"}}
                except (KeyError,ValueError) as exc:
                    messages.append({"role":"tool","tool_call_id":call.get("id",""),"content":json.dumps({"error":str(exc)},ensure_ascii=False)})
                    continue
            try: output=_run_tool(root,name,args); payload={"ok":True,"result":output}
            except (ValueError,KeyError,OSError) as exc: payload={"ok":False,"error":str(exc)}
            messages.append({"role":"tool","tool_call_id":call.get("id",""),"content":json.dumps(payload,ensure_ascii=False)[:12000]})
    return {"text":"O agente atingiu o limite de 8 passos. Podes pedir para continuar.","messages":messages,"limit_reached":True}

async def run_agent(req, root:Path, store:PendingStore):
    messages=list(req.messages)
    if not messages or messages[-1].get("role")!="user": raise HTTPException(400,"A mensagem do utilizador está em falta.")
    system={"role":"system","content":"És o Mega Harness Agent. Usa ferramentas quando for necessário executar trabalho. Só podes aceder a projetos/. Nunca afirmes que alteraste ficheiros sem ferramenta. Ficheiros até 150 KB, apenas texto. Pede confirmação através da ferramenta antes de apagar. Não executas comandos nem programas."}
    if not messages or messages[0].get("role")!="system": messages.insert(0,system)
    return await _continue(req,root,store,messages)

async def confirm_delete(cid:str, approved:bool, store:PendingStore, root:Path):
    item=store.items.pop(cid,None)
    if item is None: raise HTTPException(404,"Confirmação expirada ou já utilizada.")
    call=item.tool_call; messages=item.messages
    if approved:
        try: out=delete_file(root,item.path); payload={"ok":True,"result":out}
        except (ValueError,OSError) as exc: payload={"ok":False,"error":str(exc)}
    else: payload={"ok":False,"cancelled":True,"message":"Utilizador recusou a eliminação."}
    messages.append({"role":"tool","tool_call_id":(call.get("id") or ""),"content":json.dumps(payload,ensure_ascii=False)})
    return await _continue(item.req,root,store,messages,0)
