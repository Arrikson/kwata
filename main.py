import os
import json
import firebase_admin
from firebase_admin import credentials, firestore, storage
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import uvicorn

# Caminho para o arquivo de chave privada
cred = credentials.Certificate("firebase-key.json")

# Verifica se o Firebase já foi inicializado
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'storageBucket': cred.project_id + ".appspot.com"
    })

# Inicializa Firestore e Storage
db = firestore.client()
bucket = storage.bucket()

app = FastAPI()

# Monta a pasta static na rota "/static"
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

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

@app.get("/admin", response_class=HTMLResponse)
async def admin_form(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

# POST para cadastrar produto
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
    # Salva a imagem no Firebase Storage
    blob = bucket.blob(imagem.filename)
    blob.upload_from_string(await imagem.read(), content_type=imagem.content_type)
    imagem_url = blob.public_url  # URL pública da imagem no Firebase Storage

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

    # Adiciona o produto ao Firestore
    produtos_ref = db.collection('produtos')
    produtos_ref.add(produto)

    from fastapi.responses import RedirectResponse

return RedirectResponse(url="/admin?sucesso=1", status_code=303)

# Execução local
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
