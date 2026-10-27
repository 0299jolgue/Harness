"""Bounded OpenAI tool loop for files and Z-Image-Turbo."""
from __future__ import annotations
import base64
import json
import secrets
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from workspace import (list_files, file_info, read_file, write_file, edit_file, search_files,
                       read_pdf, list_archive, read_archive_file, extract_archive,
                       create_folder, move_file, delete_file, resolve)

MAX_ROUNDS = 8
TOOLS = [
 {"type":"function","function":{"name":"list_files","description":"Lista ficheiros em projetos/.","parameters":{"type":"object","properties":{"path":{"type":"string","default":"."}},"additionalProperties":False}}},
 {"type":"function","function":{"name":"file_info","description":"Mostra tamanho, extensão e metadados de um ficheiro, incluindo ficheiros grandes.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"read_file","description":"Lê um bloco de texto UTF-8 até 8 KB. Para ficheiros grandes, continua usando o next_offset devolvido.","parameters":{"type":"object","properties":{"path":{"type":"string"},"offset":{"type":"integer","default":0},"limit":{"type":"integer","default":8192}},"required":["path"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"read_pdf","description":"Extrai texto das páginas indicadas de um PDF em projetos/; lê até 3 páginas por chamada.","parameters":{"type":"object","properties":{"path":{"type":"string"},"page":{"type":"integer","default":1},"pages":{"type":"integer","default":1}},"required":["path"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"create_file","description":"Cria um novo ficheiro de texto em projetos/ (máximo 8 MB).","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"write_file","description":"Cria ou substitui um ficheiro de texto até 8 MB em projetos/.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"edit_file","description":"Substitui uma única ocorrência de texto num ficheiro até 64 MB.","parameters":{"type":"object","properties":{"path":{"type":"string"},"old_text":{"type":"string"},"new_text":{"type":"string"}},"required":["path","old_text","new_text"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"search_files","description":"Procura texto em ficheiros de texto de projetos/, processando-os por linhas.","parameters":{"type":"object","properties":{"query":{"type":"string"},"path":{"type":"string","default":"."}},"required":["query"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"list_archive","description":"Lista nomes e tamanhos das entradas de um arquivo ZIP.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"read_archive_file","description":"Lê um bloco de até 8 KB de um ficheiro de texto dentro de um ZIP. Usa offset para continuar.","parameters":{"type":"object","properties":{"path":{"type":"string"},"member":{"type":"string"},"offset":{"type":"integer","default":0}},"required":["path","member"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"extract_archive","description":"Extrai um ZIP dentro de projetos/, bloqueando caminhos inseguros e mais de 10 GB descomprimidos.","parameters":{"type":"object","properties":{"path":{"type":"string"},"destination":{"type":"string","default":"."}},"required":["path"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"create_folder","description":"Cria uma pasta dentro de projetos/.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"move_file","description":"Move um ficheiro ou pasta dentro de projetos/.","parameters":{"type":"object","properties":{"source":{"type":"string"},"destination":{"type":"string"}},"required":["source","destination"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"generate_image","description":"Gera uma imagem com Z-Image-Turbo no Colab. Usa quando o utilizador pede para criar/desenhar uma imagem. A Base URL e chave têm de estar configuradas em Definições > Imagens.","parameters":{"type":"object","properties":{"prompt":{"type":"string"},"width":{"type":"integer","default":1024},"height":{"type":"integer","default":1024}},"required":["prompt"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"delete_file","description":"Pede confirmação individual antes de apagar um ficheiro em projetos/.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":False}}}
]

@dataclass
class Pending:
    req: Any
    messages: list[dict[str, Any]]
    tool_call: dict[str, Any]
    path: str
    image_paths: list[str] = field(default_factory=list)

class PendingStore:
    def __init__(self): self.items: dict[str, Pending] = {}

def _run_tool(root: Path, name: str, args: dict):
    funcs = {
      "list_files":lambda:list_files(root,args.get("path",".")),
      "file_info":lambda:file_info(root,args["path"]),
      "read_file":lambda:read_file(root,args["path"],args.get("offset",0),args.get("limit",24576)),
      "read_pdf":lambda:read_pdf(root,args["path"],args.get("page",1),args.get("pages",1)),
      "create_file":lambda:write_file(root,args["path"],args["content"],create_only=True),
      "write_file":lambda:write_file(root,args["path"],args["content"]),
      "edit_file":lambda:edit_file(root,args["path"],args["old_text"],args["new_text"]),
      "search_files":lambda:search_files(root,args["query"],args.get("path",".")),
      "list_archive":lambda:list_archive(root,args["path"]),
      "read_archive_file":lambda:read_archive_file(root,args["path"],args["member"],args.get("offset",0)),
      "extract_archive":lambda:extract_archive(root,args["path"],args.get("destination",".")),
      "create_folder":lambda:create_folder(root,args["path"]),
      "move_file":lambda:move_file(root,args["source"],args["destination"]),
    }
    if name not in funcs: raise ValueError("Ferramenta desconhecida.")
    return funcs[name]()

async def _model(req, messages):
    base=req.base_url.strip().rstrip("/")
    if not (base.startswith("https://") or base.startswith("http://127.0.0.1")):
        raise HTTPException(400,"A Base URL tem de usar HTTPS (ou localhost).")
    body={"model":req.model,"messages":messages,"tools":TOOLS,"tool_choice":"auto","parallel_tool_calls":False,"temperature":req.temperature,"max_tokens":req.max_tokens}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600,connect=20),follow_redirects=False) as client:
            headers={}
            if req.api_key: headers["Authorization"]=f"Bearer {req.api_key}"
            response=await client.post(base+"/chat/completions",json=body,headers=headers)
    except httpx.HTTPError as exc: raise HTTPException(502,f"Falha de ligação ao fornecedor ({type(exc).__name__}).") from None
    if response.status_code>=400: raise HTTPException(502,"Fornecedor recusou o pedido Agent. Confirma modelo e suporte de ferramentas.")
    try:return response.json()
    except ValueError:raise HTTPException(502,"Resposta inválida do fornecedor.") from None

async def _generate_image(req, root: Path, args: dict):
    base=(req.image_base_url or "").strip().rstrip("/")
    key=(req.image_api_key or "").strip()
    if not base or not key: return None
    if not base.startswith("https://") and not base.startswith("http://127.0.0.1"):
        raise ValueError("A Base URL do Z-Image tem de usar HTTPS.")
    endpoint=base if base.endswith("/v1") else base+"/v1"
    width=max(512,min(1024,int(args.get("width",1024)))); height=max(512,min(1024,int(args.get("height",1024))))
    width=round(width/16)*16; height=round(height/16)*16
    payload={"prompt":args["prompt"],"width":width,"height":height,"num_inference_steps":8}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600,connect=30),follow_redirects=False) as client:
            response=await client.post(endpoint+"/images/generations",json=payload,headers={"Authorization":f"Bearer {key}"})
    except httpx.HTTPError as exc: raise ValueError(f"Falha ao ligar ao Z-Image ({type(exc).__name__}).") from None
    if response.status_code>=400: raise ValueError(f"Z-Image recusou a geração (HTTP {response.status_code}).")
    try: data=response.json()["data"][0]["b64_json"]
    except (ValueError,KeyError,IndexError,TypeError): raise ValueError("O serviço Z-Image devolveu uma resposta sem imagem base64.") from None
    image=base64.b64decode(data,validate=True)
    if len(image)>25*1024*1024: raise ValueError("A imagem gerada excedeu 25 MB.")
    out=resolve(root,"geradas") / f"zimage-{secrets.token_hex(8)}.png"
    out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(image)
    return out.relative_to(root).as_posix()

async def _continue(req,root:Path,store:PendingStore,messages,start_round=0,image_paths=None):
    image_paths=list(image_paths or [])
    for _ in range(start_round,MAX_ROUNDS):
        result=await _model(req,messages)
        choices=result.get("choices") or []
        if not choices: raise HTTPException(502,"O fornecedor não devolveu escolhas.")
        msg=choices[0].get("message") or {}; messages.append(msg)
        calls=msg.get("tool_calls") or []
        if not calls: return {"text":msg.get("content") or "Concluído.","images":image_paths,"messages":messages}
        for call in calls:
            fn=call.get("function") or {}; name=fn.get("name","")
            try: args=json.loads(fn.get("arguments") or "{}")
            except (TypeError,ValueError): args={}
            if name=="delete_file":
                try:
                    target=resolve(root,args["path"])
                    if not target.is_file(): raise ValueError("O caminho não é um ficheiro dentro de projetos/.")
                    cid=secrets.token_urlsafe(18)
                    store.items[cid]=Pending(req,messages,call,args["path"],image_paths)
                    return {"text":msg.get("content") or "","images":image_paths,
                        "confirmation":{"id":cid,"action":"delete_file","path":args["path"],"message":f"Apagar o ficheiro {args['path']}?"}}
                except (KeyError,ValueError) as exc:
                    messages.append({"role":"tool","tool_call_id":call.get("id",""),"content":json.dumps({"error":str(exc)},ensure_ascii=False)}); continue
            if name=="generate_image":
                if not req.image_base_url or not req.image_api_key:
                    return {"text":"Para criar imagens, configura a Base URL e a chave API do Z-Image-Turbo em Definições → Imagens e volta a pedir a imagem.","images":image_paths,"needs_image_provider":True,"messages":messages}
                try:
                    path=await _generate_image(req,root,args); image_paths.append(path)
                    output={"ok":True,"image_path":path,"width":args.get("width",1024),"height":args.get("height",1024)}
                except (ValueError,KeyError,OSError) as exc: output={"ok":False,"error":str(exc)}
            else:
                try: output={"ok":True,"result":_run_tool(root,name,args)}
                except (ValueError,KeyError,OSError,zipfile.BadZipFile) as exc: output={"ok":False,"error":str(exc)}
            messages.append({"role":"tool","tool_call_id":call.get("id",""),"content":json.dumps(output,ensure_ascii=False)[:12000]})
    return {"text":"O agente atingiu o limite de 8 passos. Podes pedir para continuar.","images":image_paths,"messages":messages,"limit_reached":True}

async def run_agent(req,root:Path,store:PendingStore):
    messages=list(req.messages)
    if not messages or messages[-1].get("role")!="user": raise HTTPException(400,"A mensagem do utilizador está em falta.")
    system={"role":"system","content":"És o Mega Harness Agent. Usa ferramentas para executar ações. Só podes aceder a projetos/. Ficheiros podem ter até 10 GB; lê os textos em blocos pequenos e usa next_offset para continuar. Para PDF usa read_pdf por páginas. Para ZIP usa list_archive/read_archive_file ou extract_archive. Imagens em pedidos do utilizador podem ser analisadas se o servidor multimodal estiver configurado. Para pedidos de criação de imagem chama generate_image; se as credenciais não estiverem configuradas, pede ao utilizador que abra Definições > Imagens. Nunca digas que alteraste um ficheiro sem ferramenta. Apagar exige confirmação individual. Não executas comandos do sistema."}
    if not messages or messages[0].get("role")!="system": messages.insert(0,system)
    return await _continue(req,root,store,messages)

async def confirm_delete(cid:str,approved:bool,store:PendingStore,root:Path):
    item=store.items.pop(cid,None)
    if item is None: raise HTTPException(404,"Confirmação expirada ou já utilizada.")
    call=item.tool_call; messages=item.messages
    if approved:
        try: payload={"ok":True,"result":delete_file(root,item.path)}
        except (ValueError,OSError) as exc: payload={"ok":False,"error":str(exc)}
    else: payload={"ok":False,"cancelled":True,"message":"Utilizador recusou a eliminação."}
    messages.append({"role":"tool","tool_call_id":call.get("id") or "","content":json.dumps(payload,ensure_ascii=False)})
    return await _continue(item.req,root,store,messages,0,item.image_paths)
