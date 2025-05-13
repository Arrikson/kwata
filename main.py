from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import os
import json
from typing import List
import uvicorn

app = FastAPI()

# Monta a pasta static na rota "/static"
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuração do template Jinja2
templates = Jinja2Templates(directory="templates")

# Lista para armazenar os bilhetes já vendidos
vendas_realizadas = []

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

# Página de compra da rifa
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
    # Cria diretório static se não existir
    os.makedirs("static", exist_ok=True)

    # Salva a imagem na pasta static
    imagem_path = os.path.join("static", imagem.filename)
    with open(imagem_path, "wb") as f:
        f.write(await imagem.read())

    # Caminho acessível no HTML
    imagem_url = f"/static/{imagem.filename}"

    # Calcula os valores dependendo do input fornecido
    total_necessario = preco_aquisicao + lucro_desejado
    if preco_bilhete:
        quantidade_calculada = int(total_necessario // preco_bilhete) + 1
    elif quantidade_bilhetes:
        preco_bilhete = total_necessario / quantidade_bilhetes
        quantidade_calculada = quantidade_bilhetes
    else:
        preco_bilhete = 0
        quantidade_calculada = 0

    # Cria objeto do produto
    produto = {
        "nome": nome,
        "descricao": descricao,
        "imagem": imagem_url,
        "preco_aquisicao": preco_aquisicao,
        "lucro_desejado": lucro_desejado,
        "preco_bilhete": round(preco_bilhete, 2),
        "quantidade_bilhetes": quantidade_calculada
    }

    # Corrigido: esta linha estava com indentação errada
    produtos = []
    if os.path.exists("produtos.json"):
        with open("produtos.json", "r", encoding="utf-8") as f:
            try:
                produtos = json.load(f)
            except json.JSONDecodeError:
                produtos = []

    produtos.append(produto)

    with open("produtos.json", "w", encoding="utf-8") as f:
        json.dump(produtos, f, ensure_ascii=False, indent=4)

    return templates.TemplateResponse("admin.html", {"request": request, "mensagem": "Produto adicionado com sucesso!"})

# Para execução local
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

