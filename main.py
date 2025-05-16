import os 
import json
import firebase_admin
import uvicorn
from firebase_admin import credentials, firestore
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from uuid import uuid4
from datetime import datetime
import traceback  # ✅ Para exibir erros completos
import hashlib
from fastapi import Form
from typing import List
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO
from fastapi import Query
from fastapi.responses import JSONResponse
from pathlib import Path
from google.cloud.firestore_v1 import DocumentSnapshot
from google.protobuf.timestamp_pb2 import Timestamp



# Caminho da chave do Firebase
FIREBASE_KEY_PATH = "firebase-key.json"

# Inicializa o Firebase se ainda não estiver inicializado
if not firebase_admin._apps:
    if not os.path.exists(FIREBASE_KEY_PATH):
        raise FileNotFoundError("Arquivo firebase-key.json não encontrado. Coloque-o na raiz do projeto.")
    
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)

# Firestore
db = firestore.client()

# Inicializa FastAPI
app = FastAPI()

# Pasta de arquivos estáticos e templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

UPLOAD_DIR = os.path.join("static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

pasta_static = Path("static")  # ajuste conforme sua estrutura real
caminho_arquivo = pasta_static / "produto-refletidos.json"

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        produtos_ref = db.collection('produtos').stream()
        produtos = []
        for doc in produtos_ref:
            data = doc.to_dict()
            data["id"] = doc.id

            bilhetes_vendidos = data.get("bilhetes_vendidos", 0)
            quantidade_total = data.get("quantidade_bilhetes", 0)

            bilhetes_disponiveis = max(quantidade_total - bilhetes_vendidos, 0)

            data["bilhetes_disponiveis"] = bilhetes_disponiveis
            data["preco_bilhete"] = data.get("preco_bilhete", 0)

            produtos.append(data)
    except Exception as e:
        print("❌ Erro ao buscar produtos do Firestore:", e)
        traceback.print_exc()
        produtos = []

    return templates.TemplateResponse("index.html", {
        "request": request,
        "produtos": produtos
    })

@app.get("/admin", response_class=HTMLResponse)
async def admin_form(request: Request):
    sucesso = request.query_params.get("sucesso")
    erro = request.query_params.get("erro")
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "sucesso": sucesso,
        "erro": erro
    })

@app.post("/admin")
async def adicionar_produto(
    request: Request,
    nome: str = Form(...),
    descricao: str = Form(...),
    imagem: UploadFile = File(...),
    preco_aquisicao: float = Form(...),
    lucro_desejado: float = Form(...),
    preco_bilhete: float = Form(None),
    quantidade_bilhetes: int = Form(None),
    data_limite: str = Form(...)  # novo campo vindo do formulário
):
    try:
        print("🔧 ROTA /admin ACIONADA")
        print("📅 data_limite recebido:", data_limite)

        # ✅ Converter diretamente para datetime (Firestore aceita datetime)
        data_limite_dt = datetime.fromisoformat(data_limite)

        # Salva a imagem no servidor
        conteudo_imagem = await imagem.read()
        ext = os.path.splitext(imagem.filename)[-1]
        nome_arquivo = f"{uuid4().hex}{ext}"
        caminho_imagem = os.path.join(UPLOAD_DIR, nome_arquivo)

        with open(caminho_imagem, "wb") as f:
            f.write(conteudo_imagem)

        imagem_url = f"/static/uploads/{nome_arquivo}"
        print("📤 Imagem salva localmente em:", imagem_url)

        total_necessario = preco_aquisicao + lucro_desejado

        if preco_bilhete:
            quantidade_calculada = int(total_necessario // preco_bilhete) + 1
        elif quantidade_bilhetes:
            preco_bilhete = total_necessario / quantidade_bilhetes
            quantidade_calculada = quantidade_bilhetes
        else:
            preco_bilhete = 0
            quantidade_calculada = 0

        produto = {
            "nome": nome,
            "descricao": descricao,
            "imagem": imagem_url,
            "preco_aquisicao": preco_aquisicao,
            "lucro_desejado": lucro_desejado,
            "preco_bilhete": round(preco_bilhete, 2),
            "quantidade_bilhetes": quantidade_calculada,
            "bilhetes_vendidos": 0,
            "data_limite": data_limite_dt  # ✅ usar datetime, não Timestamp
        }

        print("📝 Produto a ser salvo:", produto)

        db.collection('produtos').add(produto)
        print("✅ Produto salvo no Firestore!")

        return RedirectResponse(url="/admin?sucesso=1", status_code=303)

    except Exception as e:
        print("❌ ERRO AO SALVAR PRODUTO:", str(e))
        traceback.print_exc()
        return RedirectResponse(url="/admin?erro=1", status_code=303)

@app.get("/pagamento-rifa.html")
async def exibir_pagamento(request: Request, produto_id: str = Query(default=None)):
    if not produto_id:
        return templates.TemplateResponse("pagamento-rifa.html", {
            "request": request,
            "erro": "Nenhum produto selecionado. Volte à página anterior e selecione um produto."
        })

    try:
        # 🔹 Carrega os dados do JSON local
        with open(caminho_arquivo, "r", encoding="utf-8") as f:
            produtos = json.load(f)

        # 🔹 Busca o produto com o ID correspondente
        dados_produto = next((p for p in produtos if p.get("id") == produto_id), None)

        if not dados_produto:
            return templates.TemplateResponse("pagamento-rifa.html", {
                "request": request,
                "erro": "Produto não encontrado no arquivo JSON."
            })

        quantidade_bilhetes = dados_produto.get("quantidade_bilhetes", 0)
        preco_bilhete = dados_produto.get("preco_bilhete", 0.0)
        preco_total = dados_produto.get("preco", 0.0)

        # 🔹 Carrega bilhetes já comprados (do Firebase, se ainda quiser manter)
        compras_ref = db.collection("compras").where("produto_id", "==", produto_id).stream()
        bilhetes_comprados = []

        for compra in compras_ref:
            data = compra.to_dict()
            numeros = data.get("numeros_bilhetes", [])
            bilhetes_comprados.extend(numeros)

        # 🔹 Calcular bilhetes disponíveis
        bilhetes_disponiveis = [
            i for i in range(1, quantidade_bilhetes + 1)
            if i not in bilhetes_comprados
        ]

        return templates.TemplateResponse("pagamento-rifa.html", {
            "request": request,
            "produto_id": produto_id,
            "preco": preco_total,
            "preco_bilhete": preco_bilhete,
            "bilhetes_disponiveis": bilhetes_disponiveis
        })

    except Exception as e:
        print("❌ Erro ao carregar dados do pagamento:", e)
        return templates.TemplateResponse("pagamento-rifa.html", {
            "request": request,
            "erro": "Erro ao carregar os dados. Verifique sua conexão e tente novamente."
        })

def converter_valores_json(data):
    """
    Função recursiva que converte tipos não serializáveis (ex: datas) para strings.
    """
    if isinstance(data, dict):
        return {k: converter_valores_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [converter_valores_json(i) for i in data]
    elif hasattr(data, "ToDatetime"):  # objeto Firestore Timestamp
        return data.ToDatetime().isoformat()
    # para objetos datetime comuns, já possuem isoformat
    elif hasattr(data, "isoformat"):
        try:
            return data.isoformat()
        except Exception:
            pass
    # para protobuf Timestamp ou objetos com método timestamp mas sem isoformat
    elif hasattr(data, "timestamp"):
        try:
            ts = data.timestamp()
            # timestamp() retorna float, converte para ISO string
            return datetime.fromtimestamp(ts).isoformat()
        except Exception:
            pass
    return data

@app.get("/gerar-produto-refletidos")
async def gerar_arquivo_produtos():
    try:
        produtos_ref = db.collection("produtos").stream()

        lista_produtos = []
        for doc in produtos_ref:
            produto = doc.to_dict()
            produto["id"] = doc.id
            produto = converter_valores_json(produto)
            lista_produtos.append(produto)

        pasta_static = Path("static")
        pasta_static.mkdir(exist_ok=True)

        caminho_arquivo = pasta_static / "produto-refletidos.json"

        with open(caminho_arquivo, "w", encoding="utf-8") as f:
            json.dump(lista_produtos, f, ensure_ascii=False, indent=4)

        # Retornar conteúdo dos produtos e info
        return JSONResponse({
            "mensagem": "Arquivo produto-refletidos.json gerado com sucesso na pasta /static.",
            "quantidade": len(lista_produtos),
            "url": "/static/produto-refletidos.json",
            "produtos": lista_produtos  # adiciona produtos no json de resposta
        })

    except Exception as e:
        erro_completo = traceback.format_exc()
        print("❌ Erro ao gerar arquivo de produtos:", erro_completo)
        return JSONResponse(
            {"erro": "Não foi possível gerar o arquivo de produtos.", "detalhes": str(e)},
            status_code=500
        )

@app.get("/produtos")
async def listar_produtos():
    try:
        produtos_ref = db.collection("produtos").stream()

        lista_produtos = []
        for doc in produtos_ref:
            produto = doc.to_dict()
            produto["id"] = doc.id
            produto = converter_valores_json(produto)
            lista_produtos.append(produto)

        return JSONResponse(content=lista_produtos)

    except Exception as e:
        erro_completo = traceback.format_exc()
        print("❌ Erro ao buscar produtos:", erro_completo)
        return JSONResponse(
            {"erro": "Não foi possível buscar os produtos.", "detalhes": str(e)},
            status_code=500
        )


@app.get("/registros", response_class=HTMLResponse)
async def listar_registros(request: Request):
    try:
        registros = []

        # 🔹 1. Coletar dados da coleção "pagamentos"
        pagamentos_ref = db.collection("pagamentos").stream()
        for doc in pagamentos_ref:
            data = doc.to_dict()
            produto_id = data.get("produto_id")
            produto_nome = "Desconhecido"

            if produto_id:
                produto_doc = db.collection("produtos").document(produto_id).get()
                if produto_doc.exists:
                    produto_nome = produto_doc.to_dict().get("nome", "Sem Nome")

            registros.append({
                "nome": data.get("nome"),
                "bi": data.get("bi"),
                "telefone": data.get("telefone", "N/A"),
                "localizacao": data.get("localizacao"),
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "produto": produto_nome,
                "quantidade_bilhetes": data.get("quantidade_bilhetes"),
                "data_envio": data.get("data_envio")
            })

        # 🔹 2. Coletar dados da coleção "compras"
        compras_ref = db.collection("compras").stream()
        for doc in compras_ref:
            data = doc.to_dict()
            produto_id = data.get("produto_id")
            produto_nome = "Desconhecido"

            if produto_id:
                produto_doc = db.collection("produtos").document(produto_id).get()
                if produto_doc.exists:
                    produto_nome = produto_doc.to_dict().get("nome", "Sem Nome")

            registros.append({
                "nome": data.get("nome"),
                "bi": data.get("bi"),
                "telefone": data.get("telefone", "N/A"),
                "localizacao": data.get("localizacao"),
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "produto": produto_nome,
                "quantidade_bilhetes": data.get("quantidade_bilhetes"),
                "data_envio": data.get("data_compra")  # campo diferente em compras
            })

        # 🔹 3. Ordenar por data mais recente
        registros.sort(key=lambda x: x["data_envio"] or "", reverse=True)

        return templates.TemplateResponse("registros.html", {
            "request": request,
            "registros": registros
        })

    except Exception as e:
        print("❌ Erro ao listar registros:", e)
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse("registros.html", {
            "request": request,
            "registros": [],
            "erro": "Erro ao carregar os registros."
        })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

