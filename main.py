import os 
import json
import firebase_admin
import uvicorn
import uuid
import random
import sys
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
from typing import List
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request, UploadFile, File, Form



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
    comprovativoURL: str  # URL do Firebase
    timestamp: str = ""   # opcional

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

@app.get("/")
def index(request: Request):
    db = firestore.client()
    produtos_ref = db.collection("produtos")
    docs = produtos_ref.stream()

    produtos = []
    for doc in docs:
        data = doc.to_dict()
        produto_id = doc.id

        # Buscar o bilhetes_disponiveis na coleção "rifas-restantes" pelo mesmo id do produto
        rifa_doc = db.collection("rifas-restantes").document(produto_id).get()
        if rifa_doc.exists:
            rifa_data = rifa_doc.to_dict()
            bilhetes_disponiveis = rifa_data.get("bilhetes_disponiveis", 0)
        else:
            bilhetes_disponiveis = 0

        produto = {
            "id": produto_id,
            "nome": data.get("nome", "Sem nome"),
            "descricao": data.get("descricao", ""),
            "preco_bilhete": data.get("preco_bilhete", 0),
            "imagem": data.get("imagem", "/static/imagem_padrao.jpg"),
            "data_limite_iso": data.get("data_limite_iso", "2025-12-31T23:59:59Z"),
            "bilhetes_disponiveis": bilhetes_disponiveis
        }
        produtos.append(produto)

    return templates.TemplateResponse("index.html", {"request": request, "produtos": produtos})

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
    data_sorteio: str = Form(...)  # ⬅️ Nome atualizado
):
    try:
        print("🔧 ROTA /admin ACIONADA")
        print("📅 data_sorteio recebido:", data_sorteio)

        # ✅ Converter diretamente para datetime (Firestore aceita datetime)
        data_sorteio_dt = datetime.fromisoformat(data_sorteio)

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
            "data_sorteio": data_sorteio_dt  # ⬅️ Nome atualizado
        }

        print("📝 Produto a ser salvo:", produto)

        # Salva produto e pega ID gerado
        doc_ref = db.collection('produtos').add(produto)[1]
        produto_id = doc_ref.id
        print(f"✅ Produto salvo no Firestore com ID: {produto_id}")

        # Chama a função para atualizar rifas restantes
        atualizar_rifas_restantes(produto_id)

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
        # 🔹 Buscar o produto no Firebase
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

        # 🔹 Buscar rifas restantes no documento específico
        rifas_restantes_doc = db.collection("rifas-restantes").document(produto_id).get()
        if rifas_restantes_doc.exists:
            bilhetes_disponiveis = rifas_restantes_doc.to_dict().get("bilhetes_disponiveis", [])
        else:
            # 🔄 Caso não exista documento, calcula com base na quantidade total e vendidos
            quantidade_bilhetes = int(dados_produto.get("quantidade_bilhetes", 0))
            bilhetes_vendidos = int(dados_produto.get("bilhetes_vendidos", 0))
            bilhetes_disponiveis = list(range(bilhetes_vendidos + 1, quantidade_bilhetes + 1))

            # ✅ Criar documento na coleção "rifas-restantes"
            db.collection("rifas-restantes").document(produto_id).set({
                "bilhetes_disponiveis": bilhetes_disponiveis,
                "atualizado_em": datetime.now().isoformat()
            })

        # 🔸 Montar contexto para o template
        contexto = {
            "request": request,
            "produto_id": produto_id,
            "nome_produto": nome_produto,
            "preco_bilhete": preco_bilhete,
            "quantidade_bilhetes": 1,
            "bilhetes_disponiveis": bilhetes_disponiveis
        }

        # ✅ Mostrar mensagem de sucesso se for redirecionado após o POST
        if sucesso == "1":
            contexto["sucesso"] = "Pagamento enviado com sucesso! Seus bilhetes foram reservados."

        return templates.TemplateResponse("pagamento-rifa.html", contexto)

    except Exception as e:
        print(f"❌ Erro ao carregar dados do Firebase: {e}")
        return templates.TemplateResponse("pagamento-rifa.html", {
            "request": request,
            "erro": "Erro ao carregar os dados. Verifique sua conexão e tente novamente."
        })

@app.post("/pagamento-rifa.html")
async def processar_pagamento_rifa(
    request: Request,
    produto_id: str = Form(...),
    nome: str = Form(...),
    numero_bi: str = Form(...),
    telefone: str = Form(...),
    bilhetes_selecionados: List[int] = Form(...),
    nome_comprovativo: str = Form(...),
    numero_comprovativo: str = Form(...),
    comprovativo: UploadFile = Form(...)
):
    try:
        # 🔍 Buscar todos os registros existentes
        registros_ref = db.collection("registros")
        registros = registros_ref.stream()

        # 🔁 Verificar se já existe nome, BI, telefone ou comprovativo duplicado
        for registro in registros:
            dados = registro.to_dict()

            if dados.get("nome") == nome:
                return templates.TemplateResponse("pagamento-rifa.html", {
                    "request": request,
                    "produto_id": produto_id,
                    "erro": "Este nome já foi usado para registro."
                })

            if dados.get("numero_bi") == numero_bi:
                return templates.TemplateResponse("pagamento-rifa.html", {
                    "request": request,
                    "produto_id": produto_id,
                    "erro": "Este número de B.I já está registrado."
                })

            if dados.get("telefone") == telefone:
                return templates.TemplateResponse("pagamento-rifa.html", {
                    "request": request,
                    "produto_id": produto_id,
                    "erro": "Este número de telefone já está registrado."
                })

            if dados.get("numero_comprovativo") == numero_comprovativo and dados.get("nome_comprovativo") == nome_comprovativo:
                return templates.TemplateResponse("pagamento-rifa.html", {
                    "request": request,
                    "produto_id": produto_id,
                    "erro": "Este comprovativo já foi utilizado por outro usuário."
                })

            bilhetes_utilizados = dados.get("bilhetes", [])
            for bilhete in bilhetes_selecionados:
                if bilhete in bilhetes_utilizados:
                    return templates.TemplateResponse("pagamento-rifa.html", {
                        "request": request,
                        "produto_id": produto_id,
                        "erro": f"O bilhete número {bilhete} já foi comprado por outro usuário."
                    })

        # ✅ Se passou nas verificações, salvar os dados no Firebase
        novo_registro = {
            "nome": nome,
            "numero_bi": numero_bi,
            "telefone": telefone,
            "bilhetes": bilhetes_selecionados,
            "nome_comprovativo": nome_comprovativo,
            "numero_comprovativo": numero_comprovativo,
            "data_envio": datetime.now().isoformat()
        }

        db.collection("registros").add(novo_registro)

        # 🔁 Atualizar lista de bilhetes restantes
        rifas_doc_ref = db.collection("rifas-restantes").document(produto_id)
        rifas_doc = rifas_doc_ref.get()
        if rifas_doc.exists:
            bilhetes_restantes = rifas_doc.to_dict().get("bilhetes_disponiveis", [])
            novos_bilhetes = [b for b in bilhetes_restantes if b not in bilhetes_selecionados]
            rifas_doc_ref.update({"bilhetes_disponiveis": novos_bilhetes})

        # ✅ Redirecionar com sucesso
        return RedirectResponse(f"/sorteio-data?produto_id={produto_id}", status_code=303)

    except Exception as e:
        print(f"❌ Erro ao processar pagamento: {e}")
        return templates.TemplateResponse("pagamento-rifa.html", {
            "request": request,
            "produto_id": produto_id,
            "erro": "Erro ao processar o pagamento. Tente novamente."
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

def converter_valores_json(data_str):
    # Aqui você pode colocar a lógica de conversão que quiser
    # Exemplo simples: apenas retornar a data se não for None
    return data_str if data_str else "Data inválida"


@app.get("/registros", response_class=HTMLResponse)
async def listar_registros(request: Request):
    try:
        registros = []

        # 🔹 1. Coletar dados da coleção "comprovativo-comprados"
        comprovativos_ref = db.collection("comprovativo-comprados").stream()
        for doc in comprovativos_ref:
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
                "quantidade_bilhetes": len(data.get("bilhetes", [])),
                "bilhetes": data.get("bilhetes", []),
                "data_compra": converter_valores_json(data.get("data_compra") or data.get("data_envio"))
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
                "bilhetes": data.get("bilhetes", []),  # opcional, pode não ter
                "data_compra": converter_valores_json(data.get("data_compra"))
            })

        # 🔹 3. Ordenar por data mais recente (pode ser None)
        registros.sort(key=lambda x: x["data_compra"] or "", reverse=True)

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

@app.get("/comprovativo-comprados")
def listar_comprovativos():
    with open(CAMINHO_JSON, "r") as f:
        dados = json.load(f)
    return JSONResponse(content=dados)


@app.post("/comprovativo-comprados")
def adicionar_comprovativo(comprovativo: Comprovativo):
    with open(CAMINHO_JSON, "r") as f:
        dados = json.load(f)

    novo_comprovativo = comprovativo.dict()
    novo_comprovativo["id"] = str(uuid.uuid4())

    dados.append(novo_comprovativo)

    with open(CAMINHO_JSON, "w") as f:
        json.dump(dados, f, indent=2)

    return {"mensagem": "Comprovativo adicionado com sucesso", "id": novo_comprovativo["id"]}

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

        # Verificação de bilhetes duplicados
        for bilhete in bilhetes:
            query = list(
                rifas_ref.where("produto_id", "==", produto_id)
                         .where("bilhete", "==", bilhete)
                         .stream()
            )
            if query:
                conflitos.append(f"Bilhete {bilhete} já foi comprado.")

        # Verificação de B.I duplicado
        bi_conf = list(
            rifas_ref.where("produto_id", "==", produto_id)
                     .where("bi", "==", bi)
                     .limit(1)
                     .stream()
        )
        if bi_conf:
            conflitos.append(f"Nº do B.I {bi} já realizou uma compra para este produto.")

        # Verificação de nome duplicado
        nome_conf = list(
            rifas_ref.where("produto_id", "==", produto_id)
                     .where("nome", "==", nome)
                     .limit(1)
                     .stream()
        )
        if nome_conf:
            conflitos.append(f"Nome {nome} já está registrado neste sorteio.")

        if conflitos:
            erro_msg = " | ".join(conflitos)
            return HTMLResponse(content=f"<h2>Erro:</h2><p>{erro_msg}</p>", status_code=400)

        # Caminho da pasta de destino
        pasta = os.path.join("static", "static", "comprovativos")
        os.makedirs(pasta, exist_ok=True)

        # Verificar formato do arquivo
        file_ext = comprovativo.filename.split(".")[-1].lower()
        if file_ext not in ["pdf", "jpg", "jpeg", "png"]:
            return HTMLResponse(content="<h2>Erro:</h2><p>Formato de arquivo não suportado.</p>", status_code=400)

        # Salvar o comprovativo
        filename = f"{uuid4()}.{file_ext}"
        file_path = os.path.join(pasta, filename)
        with open(file_path, "wb") as f:
            f.write(await comprovativo.read())

        # Registrar cada bilhete no Firebase
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
                "comprovativo_path": filename
            })

        # 🔍 Obter a data do sorteio do produto
        produto_doc = db.collection("produtos").document(produto_id).get()
        if not produto_doc.exists:
            return HTMLResponse(content="<h2>Erro:</h2><p>Produto não encontrado.</p>", status_code=404)

        produto_data = produto_doc.to_dict()
        data_fim_sorteio = produto_data.get("data_sorteio")

        if not data_fim_sorteio:
            return HTMLResponse(content="<h2>Erro:</h2><p>Data do sorteio não definida para este produto.</p>", status_code=500)

        # ✅ Renderizar página com cronômetro
        return templates.TemplateResponse("sorteio-data.html", {
            "request": request,
            "data_fim_sorteio": data_fim_sorteio
        })

    except Exception as e:
        return HTMLResponse(content=f"<h2>Erro Interno:</h2><pre>{str(e)}</pre>", status_code=500)

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
        

@app.get("/sorteio-data", response_class=HTMLResponse)
async def sorteio_data_get(request: Request, produto_id: str = Query(...)):
    try:
        produto_doc = db.collection("produtos").document(produto_id).get()
        if not produto_doc.exists:
            return HTMLResponse(content="<h2>Erro:</h2><p>Produto não encontrado.</p>", status_code=404)

        produto_data = produto_doc.to_dict()
        data_sorteio = produto_data.get("data_sorteio")
        data_fim_sorteio = produto_data.get("data_fim_sorteio", data_sorteio)  # usa a mesma se fim não existir

        if not data_sorteio:
            return HTMLResponse(content="<h2>Erro:</h2><p>Data do sorteio não definida.</p>", status_code=500)

        return templates.TemplateResponse("sorteio-data.html", {
            "request": request,
            "produto_id": produto_id,
            "data_sorteio": data_sorteio,
            "data_fim_sorteio": data_fim_sorteio
        })

    except Exception as e:
        return HTMLResponse(content=f"<h2>Erro Interno:</h2><pre>{str(e)}</pre>", status_code=500)

@app.post("/sorteio-data", response_class=JSONResponse)
async def sorteio_data_post(produto_id: str = Form(...)):
    try:
        rifas_ref = db.collection("rifas-compradas")
        comprovativos = list(
            rifas_ref.where("produto_id", "==", produto_id).stream()
        )

        if not comprovativos:
            return JSONResponse(status_code=404, content={"erro": "Nenhum comprovativo encontrado para este produto."})

        # Escolhe um vencedor aleatório
        escolhido = random.choice(comprovativos)
        dados = escolhido.to_dict()

        # Busca o nome do produto na coleção "produtos"
        produto_doc = db.collection("produtos").document(produto_id).get()
        nome_produto = "Produto desconhecido"
        if produto_doc.exists:
            nome_produto = produto_doc.to_dict().get("nome", nome_produto)

        return {
            "nome": dados.get("nome", "Desconhecido"),
            "numero_bilhete": dados.get("bilhete", "N/A"),
            "produto": nome_produto
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"erro": f"Erro interno: {str(e)}"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

