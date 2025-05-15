import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import uvicorn
from uuid import uuid4

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

# Página inicial
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    produtos = []
    if os.path.exists("produtos.json"):
        with open("produtos.json", "r", encoding="utf-8") as f:
            try:
                produtos = json.load(f)
            except json.JSONDecodeError:
                produtos = []
    return templates.TemplateResponse("index.html", {"request": request, "produtos": produtos})

# Página do formulário de admin
@app.get("/admin", response_class=HTMLResponse)
async def admin_form(request: Request):
    sucesso = request.query_params.get("sucesso")
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "sucesso": sucesso
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
    quantidade_bilhetes: int = Form(None)
):
    try:
        print("🔧 ROTA /admin ACIONADA")
        conteudo_imagem = await imagem.read()
        print("📷 Imagem carregada:", imagem.filename)

        # Salvar imagem localmente
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
            "quantidade_bilhetes": quantidade_calculada
        }

        print("📝 Produto a ser salvo:", produto)

        db.collection('produtos').add(produto)
        print("✅ Produto salvo no Firestore!")

        return RedirectResponse(url="/admin?sucesso=1", status_code=303)

    except Exception as e:
        print("❌ ERRO AO SALVAR PRODUTO:", str(e))
        return templates.TemplateResponse("admin.html", {
            "request": request,
            "erro": "Erro ao cadastrar produto. Verifique os campos e tente novamente."
        })

# Execução local
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
