import os 
import json
import firebase_admin
import uvicorn
import uuid
import random
import sys
import traceback
import io
import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4
from firebase_admin import credentials, firestore
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from uuid import uuid4
from datetime import datetime
from fastapi import Form
from typing import List
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO
from fastapi import Query
from fastapi.responses import JSONResponse
from pathlib import Path
from google.cloud.firestore_v1 import DocumentSnapshot
from google.protobuf.timestamp_pb2 import Timestamp
from typing import List
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request, UploadFile, File, Form
from google.cloud.firestore_v1.base_document import DocumentSnapshot
from pydantic import BaseModel




# Caminho da chave do Firebase
FIREBASE_KEY_PATH = "firebase-key.json"
CAMINHO_ARQUIVO = "static/produto-refletidos.json"
# Define o caminho onde os arquivos serão salvos
CAMINHO_PASTA_COMPROVATIVOS = "static/static/comprovativos"

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Caminho onde serão salvos os dados
CAMINHO_JSON = "comprovativo_comprados.json"

# Criar arquivo se não existir
if not os.path.exists(CAMINHO_JSON):
    with open(CAMINHO_JSON, "w") as f:
        json.dump([], f)

class Comprovativo(BaseModel):
    nome: str
    bi: str
    telefone: str
    latitude: str
    longitude: str
    bilhetes: List[int]
    comprovativoURL: str 
    timestamp: str = ""   

def atualizar_rifas_restantes(produto_id: str):
    try:
        print(f"🔄 Atualizando rifas restantes para produto: {produto_id}")
        doc_ref = db.collection("produtos").document(produto_id)
        doc = doc_ref.get()

        if not doc.exists:
            print("❌ Produto não encontrado.")
            return

        produto = doc.to_dict()
        quantidade_total = int(produto.get("quantidade_bilhetes", 0))

        comprovativos_ref = db.collection("comprovativo-comprados").where("produto_id", "==", produto_id).stream()

        bilhetes_comprados = set()
        for comprovativo in comprovativos_ref:
            dados = comprovativo.to_dict()
            bilhetes = dados.get("bilhetes", [])
            bilhetes_comprados.update(bilhetes)

        todos_bilhetes = set(range(1, quantidade_total + 1))
        bilhetes_disponiveis = sorted(list(todos_bilhetes - bilhetes_comprados))

        db.collection("rifas-restantes").document(produto_id).set({
            "bilhetes_disponiveis": bilhetes_disponiveis,
            "atualizado_em": datetime.now().isoformat()
        })

        print(f"✅ Rifas restantes atualizadas com sucesso. Restam: {len(bilhetes_disponiveis)} bilhetes.")

    except Exception as e:
        print("❌ Erro ao atualizar rifas:")
        traceback.print_exc()
        
cred_json = os.environ.get("FIREBASE_CONFIG")

if cred_json is None:
    raise ValueError("A variável FIREBASE_CONFIG não foi encontrada.")

cred_dict = json.loads(cred_json)
cred_dict["private_key"] = cred_dict["private_key"].replace('\\n', '\n')

cred = credentials.Certificate(cred_dict)

def atualizar_contadores(id_produto):
    # Buscar bilhetes comprados do produto específico
    comprados_snapshot = db.collection("rifas-compradas").where("id_produto", "==", id_produto).stream()
    
    bilhetes_comprados = []
    for doc in comprados_snapshot:
        dados = doc.to_dict()
        bilhete = dados.get("bilhete")
        
        # Se o campo "bilhete" existir e for um único valor
        if isinstance(bilhete, (str, int)):
            bilhetes_comprados.append(str(bilhete))
        # Se for uma lista de bilhetes
        elif isinstance(bilhete, list):
            bilhetes_comprados.extend([str(b) for b in bilhete if isinstance(b, (str, int))])

    total_comprados = len(bilhetes_comprados)

    # Buscar bilhetes disponíveis do produto específico
    restantes_doc = db.collection("rifas-restantes").document(id_produto).get()
    bilhetes_disponiveis = []
    if restantes_doc.exists:
        bilhetes_disponiveis = restantes_doc.to_dict().get("bilhetes_disponiveis", [])

    # Calcular bilhetes sobrando
    bilhetes_sobrando = [str(b) for b in bilhetes_disponiveis if str(b) not in bilhetes_comprados]

    # Buscar o nome do produto da coleção "produtos"
    nome_produto = "Desconhecido"
    produto_doc = db.collection("produtos").document(id_produto).get()
    if produto_doc.exists:
        nome_produto = produto_doc.to_dict().get("nome", "Sem nome")

    # Atualizar contadores no Firestore
    db.collection("contadores").document(id_produto).set({
        "id_produto": id_produto,
        "nome_produto": nome_produto,
        "total_comprados": total_comprados,
        "bilhetes_comprados": bilhetes_comprados,
        "bilhetes_sobrando": bilhetes_sobrando,
        "atualizado_em": firestore.SERVER_TIMESTAMP
    })

    print(f"Contadores do produto '{nome_produto}' ({id_produto}) atualizados com sucesso!")


def atualizar_contadores_todos_produtos():
    produtos = db.collection("produtos").stream()
    for produto in produtos:
        atualizar_contadores(produto.id)


if __name__ == "__main__":
    atualizar_contadores_todos_produtos()

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/principal", response_class=HTMLResponse)
async def exibir_principal(request: Request):
    produtos_ref = db.collection("produtos")
    docs = produtos_ref.stream()
    imagens = [
        doc.to_dict().get("imagem")
        for doc in docs
        if doc.to_dict().get("imagem")  # Garante que a chave existe
    ]
    return templates.TemplateResponse("principal.html", {
        "request": request,
        "imagens": imagens
    })

@app.post("/principal", response_class=HTMLResponse)
async def processar_principal(request: Request):
    form_data = await request.form()
    return templates.TemplateResponse("principal.html", {
        "request": request,
        "mensagem": "Formulário recebido!"
    })


@app.get("/contrato", response_class=HTMLResponse)
async def contrato(request: Request):
    return templates.TemplateResponse("contrato.html", {"request": request})


@app.get("/sorteio", response_class=HTMLResponse)
async def sorteio(request: Request):
    return templates.TemplateResponse("sorte.html", {"request": request})

@app.get("/sobre", response_class=HTMLResponse)
async def sobre_nos(request: Request):
    return templates.TemplateResponse("sobre.html", {"request": request})

@app.get("/inscritos", response_class=HTMLResponse)
async def exibir_inscritos(request: Request):
    return templates.TemplateResponse("inscritos.html", {"request": request})

@app.get("/listar-inscritos")
async def listar_inscritos():
    docs = db.collection("rifas-compradas").stream()
    inscritos = [{"nome": doc.to_dict().get("nome"), "data_envio": doc.to_dict().get("data_envio")} for doc in docs]
    return inscritos


# ✅ Classe que define os dados esperados no comentário
class ComentarioRequest(BaseModel):
    nome: str
    telefone: str
    comentario: str

@app.get("/listar-comentarios")
async def listar_comentarios():
    docs = db.collection("comentarios").stream()
    comentarios = []
    for doc in docs:
        data = doc.to_dict()
        data['id'] = doc.id
        comentarios.append(data)
    return comentarios

@app.post("/comentar")
async def comentar(dados: ComentarioRequest):
    usuarios = db.collection("rifas-compradas") \
                .where("nome", "==", dados.nome) \
                .where("telefone", "==", dados.telefone) \
                .stream()

    validado = any(True for _ in usuarios)
    if not validado:
        return JSONResponse(status_code=403, content={"message": "Usuário não encontrado."})

    db.collection("comentarios").add({
        "nome": dados.nome,
        "telefone": dados.telefone,
        "comentario": dados.comentario,
        "oculto": False
    })

    return {"message": "Comentário enviado com sucesso."}

@app.post("/ocultar-comentario/{id}")
async def ocultar_comentario(id: str):
    db.collection("comentarios").document(id).update({"oculto": True})
    return {"message": "Comentário ocultado."}

@app.delete("/apagar-comentario/{id}")
async def apagar_comentario(id: str):
    db.collection("comentarios").document(id).delete()
    return {"message": "Comentário apagado."}

@app.get("/produtos_disponiveis")
def index(request: Request):
    db = firestore.client()
    produtos_ref = db.collection("produtos")
    docs = produtos_ref.stream()

    produtos = []
    for doc in docs:
        data = doc.to_dict()
        produto_id = doc.id

        # Buscar o bilhetes_disponiveis
        rifa_doc = db.collection("rifas-restantes").document(produto_id).get()
        bilhetes_disponiveis = rifa_doc.to_dict().get("bilhetes_disponiveis", 0) if rifa_doc.exists else 0

        # Corrigir: usar data_sorteio como campo de data
        data_sorteio = data.get("data_sorteio")
        if isinstance(data_sorteio, datetime):
            data_sorteio_iso = data_sorteio.isoformat()
        else:
            # Caso não esteja presente ou esteja num formato inválido
            data_sorteio_iso = "2025-12-31T23:59:59Z"

        produto = {
            "id": produto_id,
            "nome": data.get("nome", "Sem nome"),
            "descricao": data.get("descricao", ""),
            "preco_bilhete": data.get("preco_bilhete", 0),
            "imagem": data.get("imagem", "/static/imagem_padrao.jpg"),
            "data_limite_iso": data_sorteio_iso,  # mantém o nome para o HTML usar igual
            "bilhetes_disponiveis": bilhetes_disponiveis
        }
        produtos.append(produto)

    return templates.TemplateResponse("produtos_disponiveis.html", {"request": request, "produtos": produtos})
    

@app.get("/admin", response_class=HTMLResponse) 
async def admin_form(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

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
    data_sorteio: str = Form(...)
):
    try:
        print("🔧 ROTA /admin ACIONADA")
        print("📅 data_sorteio recebido:", data_sorteio)

        data_sorteio_dt = datetime.fromisoformat(data_sorteio)

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
            "data_sorteio": data_sorteio_dt
        }

        print("📝 Produto a ser salvo:", produto)

        doc_ref = db.collection('produtos').add(produto)[1]
        produto_id = doc_ref.id
        print(f"✅ Produto salvo no Firestore com ID: {produto_id}")

        # ✅ Cria/atualiza na coleção "produtos-futuros" se a data for futura
        agora = datetime.now()
        if data_sorteio_dt > agora:
            db.collection("produtos-futuros").document(produto_id).set({
                "nome": nome,
                "preco_bilhete": round(preco_bilhete, 2),
                "quantidade_bilhetes": quantidade_calculada,
                "data_sorteio": data_sorteio_dt.isoformat(),
                "atualizado_em": agora.isoformat()
            })
            print("📁 Produto também salvo na coleção 'produtos-futuros'.")

        # ⚠️ Chame a função de atualizar rifas se existir
        # atualizar_rifas_restantes(produto_id)

        return RedirectResponse(url="/admin?sucesso=1", status_code=303)

    except Exception as e:
        print(f"❌ Erro ao adicionar produto: {e}")
        return RedirectResponse(url="/admin?erro=1", status_code=303)


@app.get("/pagamento-rifa.html", response_class=HTMLResponse)
async def pagamento_rifa(request: Request, produto_id: str = Query(default=None), sucesso: str = Query(default=None)):
    if not produto_id:
        return templates.TemplateResponse("pagamento-rifa.html", {
            "request": request,
            "erro": "Nenhum produto selecionado. Volte à página anterior e selecione um produto."
        })

    try:
        doc_ref = db.collection("produtos").document(produto_id)
        doc = doc_ref.get()

        if not doc.exists:
            return templates.TemplateResponse("pagamento-rifa.html", {
                "request": request,
                "erro": "Produto não encontrado no Firebase."
            })

        dados_produto = doc.to_dict()
        nome_produto = dados_produto.get("nome", "Produto")
        preco_bilhete = float(dados_produto.get("preco_bilhete", 0.00))

        rifas_restantes_doc = db.collection("rifas-restantes").document(produto_id).get()
        if rifas_restantes_doc.exists:
            bilhetes_disponiveis = rifas_restantes_doc.to_dict().get("bilhetes_disponiveis", [])
        else:
            quantidade_bilhetes = int(dados_produto.get("quantidade_bilhetes", 0))
            bilhetes_vendidos = int(dados_produto.get("bilhetes_vendidos", 0))
            bilhetes_disponiveis = list(range(bilhetes_vendidos + 1, quantidade_bilhetes + 1))

            db.collection("rifas-restantes").document(produto_id).set({
                "bilhetes_disponiveis": bilhetes_disponiveis,
                "atualizado_em": datetime.now().isoformat()
            })

        rifas_compradas_ref = db.collection("rifas-compradas").where("produto_id", "==", produto_id)
        rifas_compradas_docs = rifas_compradas_ref.stream()
        bilhetes_indisponiveis = []

        for doc in rifas_compradas_docs:
            dados = doc.to_dict()
            bilhete = dados.get("bilhete")
            if isinstance(bilhete, list):
                bilhetes_indisponiveis.extend(bilhete)
            elif isinstance(bilhete, int) or isinstance(bilhete, str):
                bilhetes_indisponiveis.append(int(bilhete))

        bilhetes_indisponiveis = list(set(int(b) for b in bilhetes_indisponiveis if str(b).isdigit()))

        contexto = {
            "request": request,
            "produto_id": produto_id,
            "nome_produto": nome_produto,
            "preco_bilhete": preco_bilhete,
            "quantidade_bilhetes": 1,
            "bilhetes_disponiveis": bilhetes_disponiveis,
            "bilhetes_indisponiveis": bilhetes_indisponiveis
        }

        if sucesso == "1":
            contexto["sucesso"] = "Pagamento enviado com sucesso! Seus bilhetes foram reservados."

        # ➕ NOVO CÓDIGO AQUI: cria a tabela "compras-futuras" se a data de sorteio for futura
        data_sorteio_str = dados_produto.get("data_sorteio")
        if data_sorteio_str:
            try:
                data_sorteio = datetime.fromisoformat(data_sorteio_str)
                agora = datetime.now()
                if data_sorteio > agora:
                    nova_compra = {
                        "produto_id": produto_id,
                        "nome_comprador": "nome_comprador",         
                        "numero_bilhete": 999,                    
                        "bi_comprador": "000000000LA000",         
                        "data_compra": agora.isoformat()
                    }
                    db.collection("compras-futuras").add(nova_compra)
            except Exception as erro_data:
                print(f"⚠️ Erro ao processar data de sorteio: {erro_data}")

        return templates.TemplateResponse("pagamento-rifa.html", contexto)

    except Exception as e:
        print(f"❌ Erro ao carregar dados do Firebase: {e}")
        return templates.TemplateResponse("pagamento-rifa.html", {
            "request": request,
            "erro": "Erro ao carregar os dados. Verifique sua conexão e tente novamente."
        })


@app.post("/pagamento-rifa.html")
async def registrar_pagamento(
    request: Request,
    produto_id: str = Form(...),
    nome_comprador: str = Form(...),
    bi_comprador: str = Form(...),
    numero_bilhete: int = Form(...),
    latitude: str = Form(default=None),
    longitude: str = Form(default=None)
):
    try:
        doc_ref = db.collection("produtos").document(produto_id)
        doc = doc_ref.get()

        if not doc.exists:
            return templates.TemplateResponse("pagamento-rifa.html", {
                "request": request,
                "erro": "Produto não encontrado. Tente novamente."
            })

        dados_produto = doc.to_dict()
        data_sorteio_str = dados_produto.get("data_sorteio")

        if data_sorteio_str:
            try:
                data_sorteio = datetime.fromisoformat(data_sorteio_str)
                agora = datetime.now()

                if data_sorteio > agora:
                    nova_compra = {
                        "produto_id": produto_id,
                        "nome_comprador": nome_comprador,
                        "bi_comprador": bi_comprador,
                        "numero_bilhete": numero_bilhete,
                        "data_compra": agora.isoformat(),
                        "latitude": latitude,
                        "longitude": longitude
                    }
                    db.collection("compras-futuras").add(nova_compra)
                    return RedirectResponse(f"/pagamento-rifa.html?produto_id={produto_id}&sucesso=1", status_code=303)
                else:
                    return templates.TemplateResponse("pagamento-rifa.html", {
                        "request": request,
                        "erro": "O sorteio já aconteceu ou está acontecendo agora."
                    })

            except Exception as e:
                print(f"Erro ao converter data: {e}")
                return templates.TemplateResponse("pagamento-rifa.html", {
                    "request": request,
                    "erro": "Data de sorteio inválida."
                })

        else:
            return templates.TemplateResponse("pagamento-rifa.html", {
                "request": request,
                "erro": "Produto sem data de sorteio definida."
            })

    except Exception as e:
        print(f"❌ Erro ao registrar pagamento: {e}")
        return templates.TemplateResponse("pagamento-rifa.html", {
            "request": request,
            "erro": "Erro ao registrar a compra. Tente novamente."
        })
        

from fastapi import FastAPI, Form, File, UploadFile, Request
from fastapi.responses import HTMLResponse
from uuid import uuid4
from datetime import datetime
import os

@app.post("/enviar-comprovativo")
async def enviar_comprovativo(
    request: Request,
    nome: str = Form(...),
    bi: str = Form(...),
    telefone: str = Form(...),
    latitude: str = Form(...),
    longitude: str = Form(...),
    produto_id: str = Form(...),
    comprovativo: UploadFile = File(...),
    bilhetes: list[str] = Form(...)
):
    try:
        rifas_ref = db.collection("rifas-compradas")
        conflitos = []

        for bilhete in bilhetes:
            query = list(
                rifas_ref.where("produto_id", "==", produto_id)
                         .where("bilhete", "==", bilhete)
                         .stream()
            )
            if query:
                conflitos.append(f"Bilhete {bilhete} já foi comprado.")

        bi_conf = list(
            rifas_ref.where("produto_id", "==", produto_id)
                     .where("bi", "==", bi)
                     .limit(1)
                     .stream()
        )
        if bi_conf:
            conflitos.append(f"Nº do B.I {bi} já realizou uma compra para este produto.")

        nome_conf = list(
            rifas_ref.where("produto_id", "==", produto_id)
                     .where("nome", "==", nome)
                     .limit(1)
                     .stream()
        )
        if nome_conf:
            conflitos.append(f"Nome {nome} já está registrado neste sorteio.")

        comprovativo_duplicado = list(
            rifas_ref.where("comprovativo_path", "==", comprovativo.filename).stream()
        )
        if comprovativo_duplicado:
            conflitos.append(f"O comprovativo '{comprovativo.filename}' já foi usado. Por favor, envie outro diferente.")

        if conflitos:
            erro_msg = """
            <div style='
                background-color: #fff5f5;
                padding: 15px;
                border-left: 6px solid #f87171;
                border-radius: 8px;
                color: #7f1d1d;
                font-family: sans-serif;
                max-width: 600px;
                margin: 20px auto;
            '>
                <strong style='font-size: 1.1em;'>⚠️ Atenção:</strong>
                <ul style='padding-left: 20px; margin-top: 10px;'>
            """
            for conflito in conflitos:
                erro_msg += f"<li>{conflito}</li>"
            erro_msg += "</ul></div>"
            return HTMLResponse(content=erro_msg, status_code=400)

        # Salvar comprovativo
        pasta = os.path.join("static", "static", "comprovativos")
        os.makedirs(pasta, exist_ok=True)

        file_ext = comprovativo.filename.split(".")[-1].lower()
        if file_ext not in ["pdf", "jpg", "jpeg", "png"]:
            return HTMLResponse(content="<h2>Erro:</h2><p>Formato de arquivo não suportado.</p>", status_code=400)

        filename = f"{uuid4()}.{file_ext}"
        file_path = os.path.join(pasta, filename)
        with open(file_path, "wb") as f:
            f.write(await comprovativo.read())

        # Buscar dados do produto
        try:
            produto_doc = db.collection("produtos").document(produto_id).get()
            if not produto_doc.exists:
                return HTMLResponse(content="<h2>Erro:</h2><p>Produto não encontrado.</p>", status_code=404)

            produto_data = produto_doc.to_dict()
            data_sorteio_raw = produto_data.get("data_sorteio")
            imagem_produto = produto_data.get("imagem", "")  # busca a imagem do produto

            if isinstance(data_sorteio_raw, datetime):
                data_sorteio = data_sorteio_raw
            elif isinstance(data_sorteio_raw, str):
                try:
                    if "T" not in data_sorteio_raw:
                        data_sorteio_raw = data_sorteio_raw.replace(" ", "T")
                    data_sorteio = datetime.fromisoformat(data_sorteio_raw)
                except ValueError:
                    data_sorteio = datetime(2025, 12, 31, 23, 59, 59)
            else:
                data_sorteio = datetime(2025, 12, 31, 23, 59, 59)

        except Exception as e:
            data_sorteio = datetime(2025, 12, 31, 23, 59, 59)
            imagem_produto = ""

        # Salvar dados no Firestore
        dados_ref = db.collection("Dados")

        for bilhete in bilhetes:
            rifas_ref.add({
                "nome": nome,
                "bi": bi,
                "telefone": telefone,
                "latitude": latitude,
                "longitude": longitude,
                "produto_id": produto_id,
                "bilhete": bilhete,
                "data_envio": datetime.utcnow().isoformat(),
                "comprovativo_path": comprovativo.filename,
                "comprovativo_salvo": filename
            })
            dados_ref.add({
                "produto_id": produto_id,
                "nome": nome,
                "bilhete": bilhete,
                "data_registro": datetime.utcnow().isoformat(),
                "data_fim_sorteio": data_sorteio.isoformat(),
                "imagem_produto": imagem_produto
            })

        registros_ref = db.collection("registros")
        registros_ref.add({
            "nome_do_comprador": nome,
            "produto_id": produto_id,
            "bilhetes": bilhetes,
            "data_envio": datetime.utcnow().isoformat()
        })

        return HTMLResponse(content="""
            <div style='
                background-color: #f0fdf4;
                padding: 15px;
                border-left: 6px solid #22c55e;
                border-radius: 8px;
                color: #166534;
                font-family: sans-serif;
                max-width: 600px;
                margin: 20px auto;
            '>
                <strong style='font-size: 1.1em;'>✅ Sucesso:</strong>
                <p>Comprovativo enviado com sucesso!</p>
            </div>
        """, status_code=200)

    except Exception as e:
        return HTMLResponse(content=f"<h2>Erro Interno:</h2><pre>{str(e)}</pre>", status_code=500)

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
    
@app.post("/atualizar-data-sorteio")
async def atualizar_data_sorteio(produto_id: str = Form(...), data_sorteio: str = Form(...)):
    try:
        doc_ref = db.collection("produtos").document(produto_id)
        doc = doc_ref.get()

        if not doc.exists:
            return HTMLResponse("Produto não encontrado.", status_code=404)

        # Atualizar campo 'data_sorteio' no documento
        doc_ref.update({
            "data_sorteio": data_sorteio  # pode ser string no formato ISO ou datetime
        })

        # Redirecionar ou retornar sucesso
        return RedirectResponse(url=f"/pagamento-rifa.html?produto_id={produto_id}&sucesso=1", status_code=HTTP_302_FOUND)

    except Exception as e:
        print(f"❌ Erro ao atualizar data do sorteio: {e}")
        return HTMLResponse("Erro ao atualizar data do sorteio.", status_code=500)

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

def converter_valores_json(data_str):
    # Aqui você pode colocar a lógica de conversão que quiser
    # Exemplo simples: apenas retornar a data se não for None
    return data_str if data_str else "Data inválida"

@app.post("/comprovativos/")
async def enviar_comprovativo(
    nome: str = Form(...),
    bi: str = Form(...),
    telefone: str = Form(...),
    latitude: str = Form(""),
    longitude: str = Form(""),
    bilhetes: List[int] = Form(...),
    comprovativo: UploadFile = File(...)
):
    # Validação do tamanho
    contents = await comprovativo.read()
    if len(contents) > 32 * 1024:
        raise HTTPException(status_code=400, detail="Comprovativo maior que 32 KB.")

    # Cria a pasta se não existir
    os.makedirs(CAMINHO_PASTA_COMPROVATIVOS, exist_ok=True)

    # Salva o arquivo na pasta local
    ext = comprovativo.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    caminho_arquivo = os.path.join(CAMINHO_PASTA_COMPROVATIVOS, filename)
    with open(caminho_arquivo, "wb") as f:
        f.write(contents)

    agora = datetime.utcnow()

    # Salva os dados no Firebase Firestore
    doc_ref = db.collection("comprovativo-comprados").document()
    doc_ref.set({
        "nome": nome,
        "bi": bi,
        "telefone": telefone,
        "latitude": latitude,
        "longitude": longitude,
        "bilhetes": bilhetes,
        "timestamp": agora,
        "data_compra": agora.isoformat(),  # ✅ novo campo padronizado
        "caminho_local": caminho_arquivo
    })

    return JSONResponse({"msg": "Comprovativo enviado com sucesso."})

@app.get("/comprovativos/")
def listar_comprovativos():
    docs = db.collection("comprovativo-comprados").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    lista = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        lista.append(d)
    return lista
    

@app.post("/comprar-bilhete")
async def comprar_bilhete(
    request: Request,
    produto_id: str = Form(...),
    nome: str = Form(...),
    bi: str = Form(...),
    telefone: str = Form(...),
    latitude: str = Form(...),
    longitude: str = Form(...),
    bilhetes_comprados: List[int] = Form(...),
    comprovativo: UploadFile = File(...)
):
    try:
        # 1. Salvar o comprovativo no servidor com extensão correta
        conteudo = await comprovativo.read()
        ext = os.path.splitext(comprovativo.filename)[-1]
        nome_arquivo = f"{uuid4().hex}{ext}"
        caminho_comprovativo = os.path.join(CAMINHO_PASTA_COMPROVATIVOS, nome_arquivo)
        os.makedirs(CAMINHO_PASTA_COMPROVATIVOS, exist_ok=True)
        with open(caminho_comprovativo, "wb") as f:
            f.write(conteudo)

        comprovativo_url = f"/static/comprovativos/{nome_arquivo}"  # ajuste se usar Firebase Storage

        agora = datetime.utcnow()

        # 2. Salvar dados da compra na coleção "comprovativo-comprados" no Firestore
        compra = {
            "nome": nome,
            "bi": bi,
            "telefone": telefone,
            "latitude": latitude,
            "longitude": longitude,
            "produto_id": produto_id,
            "bilhetes": bilhetes_comprados,
            "comprovativoURL": comprovativo_url,
            "data_compra": agora.isoformat(),  # ✅ data legível
            "timestamp": agora                 # ✅ útil para ordenação
        }
        db.collection("comprovativo-comprados").add(compra)

        # 3. Atualizar bilhetes vendidos no produto
        produto_ref = db.collection("produtos").document(produto_id)
        produto_doc = produto_ref.get()
        if not produto_doc.exists:
            return templates.TemplateResponse("pagamento-rifa.html", {
                "request": request,
                "erro": "Produto não encontrado"
            })

        produto_data = produto_doc.to_dict()
        bilhetes_vendidos_atuais = produto_data.get("bilhetes_vendidos", 0)
        bilhetes_novos = len(bilhetes_comprados)
        bilhetes_vendidos_atualizado = bilhetes_vendidos_atuais + bilhetes_novos
        produto_ref.update({"bilhetes_vendidos": bilhetes_vendidos_atualizado})

        # 4. Atualizar rifas restantes
        atualizar_rifas_restantes(produto_id)

        # 5. Redirecionar para página de sucesso
        return RedirectResponse(url=f"/pagamento-rifa.html?produto_id={produto_id}&sucesso=1", status_code=303)

    except Exception as e:
        print(f"❌ Erro na compra do bilhete: {e}")
        traceback.print_exc()
        return templates.TemplateResponse("pagamento-rifa.html", {
            "request": request,
            "erro": "Erro ao processar a compra, tente novamente."
        })

@app.get("/contadores", response_class=HTMLResponse)
async def contadores(request: Request, produto_id: Optional[str] = None):
    if not produto_id:
        return templates.TemplateResponse("contadores.html", {
            "request": request,
            "rifas_compradas": [],
            "rifas_restantes": [],
            "total_vendido": 0,
            "erro": "Produto não selecionado."
        })

    # recuperar dados do produto e rifas
    doc_ref = db.collection("produtos").document(produto_id)
    doc = doc_ref.get()
    if not doc.exists:
        return templates.TemplateResponse("contadores.html", {
            "request": request,
            "rifas_compradas": [],
            "rifas_restantes": [],
            "total_vendido": 0,
            "erro": "Produto não encontrado."
        })

    dados_produto = doc.to_dict()

    rifas_restantes_doc = db.collection("rifas-restantes").document(produto_id).get()
    if rifas_restantes_doc.exists:
        rifas_restantes = rifas_restantes_doc.to_dict().get("bilhetes_disponiveis", [])
    else:
        quantidade_bilhetes = int(dados_produto.get("quantidade_bilhetes", 0))
        bilhetes_vendidos = int(dados_produto.get("bilhetes_vendidos", 0))
        rifas_restantes = list(range(bilhetes_vendidos + 1, quantidade_bilhetes + 1))

    rifas_compradas_ref = db.collection("rifas-compradas").where("produto_id", "==", produto_id)
    rifas_compradas_docs = rifas_compradas_ref.stream()
    rifas_compradas = []
    for doc in rifas_compradas_docs:
        dados = doc.to_dict()
        bilhete = dados.get("bilhete")
        if isinstance(bilhete, list):
            rifas_compradas.extend(bilhete)
        elif isinstance(bilhete, (int, str)):
            rifas_compradas.append(int(bilhete))
    rifas_compradas = sorted(set(rifas_compradas))
    total_vendido = len(rifas_compradas)

    return templates.TemplateResponse("contadores.html", {
        "request": request,
        "rifas_compradas": rifas_compradas,
        "rifas_restantes": rifas_restantes,
        "total_vendido": total_vendido,
        "erro": None,
    })


from fastapi import Form

@app.post("/contadores")
async def atualizar_contadores(
    produto_id: str = Form(...),
    rifas_compradas: str = Form(...),
    rifas_restantes: str = Form(...)
):
    # Validar que produto_id existe
    doc_ref = db.collection("produtos").document(produto_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Função para transformar string "1,2,3" em lista de inteiros
    def parse_bilhetes(bilhetes_str):
        if not bilhetes_str:
            return []
        try:
            return sorted(set(int(b.strip()) for b in bilhetes_str.split(",") if b.strip().isdigit()))
        except Exception:
            return []

    rifas_compradas_list = parse_bilhetes(rifas_compradas)
    rifas_restantes_list = parse_bilhetes(rifas_restantes)

    # Atualiza Firestore conforme seu modelo
    db.collection("rifas-compradas").document(produto_id).set({
        "bilhetes": rifas_compradas_list
    })
    db.collection("rifas-restantes").document(produto_id).set({
        "bilhetes_disponiveis": rifas_restantes_list
    })
    doc_ref.update({
        "bilhetes_vendidos": len(rifas_compradas_list)
    })

    # Redireciona para GET com query produto_id para mostrar atualizados
    url = app.url_path_for("contadores") + f"?produto_id={produto_id}"
    return RedirectResponse(url, status_code=303)
    

@app.get("/sorteios-ao-vivo", response_class=HTMLResponse)
async def sorteios_ao_vivo(request: Request):
    try:
        sorteios = []
        produtos_ref = db.collection("produtos")
        docs = produtos_ref.stream()

        for doc in docs:
            data = doc.to_dict()
            produto_id = doc.id
            nome = data.get("nome", "Produto")
            imagem = data.get("imagem", "")
            preco = data.get("preco_bilhete", 0.0)
            data_sorteio_str = data.get("data_sorteio", "")
            vencedor = None
            bilhete_vencedor = None

            if data_sorteio_str:
                try:
                    sorteio_dt = datetime.fromisoformat(data_sorteio_str)
                    if sorteio_dt.tzinfo is None:
                        sorteio_dt = sorteio_dt.replace(tzinfo=timezone.utc)

                    agora = datetime.now(timezone.utc)

                    if sorteio_dt > agora:
                        # Sorteio ainda ativo
                        sorteios.append({
                            "produto_id": produto_id,
                            "nome": nome,
                            "imagem": imagem,
                            "preco": preco,
                            "data_sorteio": data_sorteio_str,
                        })
                    else:
                        # Sorteio encerrado - registrar vencedor se ainda não registrado
                        vencedor_ref = db.collection("vencedores").document(produto_id)
                        vencedor_doc = vencedor_ref.get()
                        if not vencedor_doc.exists:
                            # Buscar o bilhete vencedor (assumindo que há uma coleção 'bilhetes')
                            bilhetes_ref = db.collection("produtos").document(produto_id).collection("bilhetes")
                            bilhetes = list(bilhetes_ref.stream())
                            if bilhetes:
                                import random
                                vencedor_bilhete = random.choice(bilhetes)
                                vencedor_data = vencedor_bilhete.to_dict()
                                vencedor = vencedor_data.get("nome_comprador", "Desconhecido")
                                bilhete_vencedor = vencedor_bilhete.id

                                # Salvar em 'vencedores'
                                vencedor_ref.set({
                                    "produto_id": produto_id,
                                    "nome_produto": nome,
                                    "nome_vencedor": vencedor,
                                    "bilhete_vencedor": bilhete_vencedor,
                                    "data_sorteio": data_sorteio_str
                                })

                except Exception as e:
                    print(f"[ERRO AO PARSEAR DATA: {data_sorteio_str}]")
                    traceback.print_exc()

        return templates.TemplateResponse("sorteios-ao-vivo.html", {
            "request": request,
            "sorteios": sorteios
        })

    except Exception as e:
        print("[ERRO GERAL NO ENDPOINT /sorteios-ao-vivo]")
        traceback.print_exc()
        return HTMLResponse(content=f"<h2>Erro ao carregar sorteios:</h2><pre>{str(e)}</pre>", status_code=500)


@app.get("/produtos-futuros", response_class=HTMLResponse)
async def produtos_futuros(request: Request):
    try:
        produtos_ref = db.collection("produtos-futuros")
        rifas_compradas_ref = db.collection("rifas-compradas")

        # Aqui estamos construindo um dicionário onde a chave é o ID do produto (produto_id)
        bilhetes_vendidos_por_produto = defaultdict(list)
        for doc in rifas_compradas_ref.stream():
            rifa = doc.to_dict()
            produto_id = rifa.get("produto_id")  # Campo correto que guarda o ID do produto
            bilhete = rifa.get("bilhete")
            if produto_id and bilhete:
                bilhetes_vendidos_por_produto[produto_id].append(str(bilhete))

        produtos = []
        for doc in produtos_ref.stream():
            produto = doc.to_dict()
            id_produto = produto.get("id")  # Esse campo deve coincidir com 'produto_id' da rifa

            try:
                quantidade = int(produto.get("quantidade_bilhetes", 0))
                produto["bilhetes_numerados"] = [str(i) for i in range(1, quantidade + 1)]
            except Exception as e:
                produto["bilhetes_numerados"] = []
                print(f"Erro ao processar bilhetes para produto {produto.get('nome')}: {e}")

            # Aqui buscamos os bilhetes vendidos para o ID correto
            produto["bilhetes_vendidos"] = bilhetes_vendidos_por_produto.get(id_produto, [])

            produtos.append(produto)

        return templates.TemplateResponse("produtos-futuros.html", {
            "request": request,
            "produtos": produtos,
            "data_atual": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        })

    except Exception as e:
        print("Erro ao carregar produtos-futuros:")
        traceback.print_exc()
        return templates.TemplateResponse("produtos-futuros.html", {
            "request": request,
            "erro": "Erro ao carregar os dados."
        })


@app.get("/vencedor/{produto_id}")
async def obter_vencedor(produto_id: str):
    try:
        produto_doc = db.collection("produtos").document(produto_id).get()
        if not produto_doc.exists:
            return {"erro": "Produto não encontrado."}

        produto_data = produto_doc.to_dict()
        data_sorteio_raw = produto_data.get("data_sorteio")
        
        if isinstance(data_sorteio_raw, datetime):
            data_sorteio_dt = data_sorteio_raw
        elif isinstance(data_sorteio_raw, str):
            if "T" not in data_sorteio_raw:
                data_sorteio_raw = data_sorteio_raw.replace(" ", "T")
            data_sorteio_dt = datetime.fromisoformat(data_sorteio_raw)
        else:
            data_sorteio_dt = datetime(2025, 12, 31, 23, 59, 59)

        agora = datetime.utcnow()
        if data_sorteio_dt > agora:
            return {"vencedor": None}  # Sorteio ainda não finalizado

        # Buscar nomes válidos
        docs = db.collection("Dados").where("produto_id", "==", produto_id).stream()
        nomes = [doc.to_dict().get("nome") for doc in docs if doc.to_dict().get("nome")]

        if not nomes:
            return {"vencedor": None}

        vencedor = random.choice(nomes)
        return {"vencedor": vencedor}
    
    except Exception as e:
        return {"erro": str(e)}
        

@app.get("/perfil", response_class=HTMLResponse)
async def perfil_form(request: Request):
    return templates.TemplateResponse("perfil.html", {"request": request, "dados": None})

@app.post("/perfil", response_class=HTMLResponse)
async def perfil_resultado(
    request: Request,
    nome: str = Form(...),
    telefone: str = Form(...),
    numero_bilhete: str = Form(...)
):
    compras_ref = db.collection("rifas-compradas")
    query = compras_ref.where("nome", "==", nome)\
                       .where("telefone", "==", telefone)\
                       .where("bilhete", "==", numero_bilhete)\
                       .stream()

    compra = None
    for doc in query:
        compra = doc.to_dict()
        break

    if compra:
        # Garantir data para o cronômetro
        data_limite_str = "2025-06-01 18:00"  # Defina corretamente
        data_limite_obj = datetime.strptime(data_limite_str, "%Y-%m-%d %H:%M")
        data_limite_iso = data_limite_obj.isoformat()
        compra["produto"] = {
            "data_limite": data_limite_str,
            "data_limite_iso": data_limite_iso
        }
        return templates.TemplateResponse("perfil.html", {
            "request": request,
            "dados": compra
        })

    return templates.TemplateResponse("perfil.html", {
        "request": request,
        "dados": None
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

