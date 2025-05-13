from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles  # 👈 Importa suporte a arquivos estáticos
import os
from typing import List
import uvicorn

app = FastAPI()

# 👇 Monta a pasta static na rota "/static"
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuração do template Jinja2
templates = Jinja2Templates(directory="templates")

# Lista para armazenar os bilhetes já vendidos (essa pode ser uma base de dados na versão final)
vendas_realizadas = []

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/comprar-rifa", response_class=HTMLResponse)
async def comprar_rifa(request: Request):
    return templates.TemplateResponse("comprar_rifa.html", {"request": request})

@app.post("/comprar-rifa")
async def processar_compra(comprovante: UploadFile = File(...), numero_rifa: int = Form(...)):
    # Verifica se o número da rifa já foi vendido
    if numero_rifa in vendas_realizadas:
        return {"message": "Número de rifa já foi vendido!"}

    # Verifica o tamanho do arquivo (máximo 32 KB)
    file_data = await comprovante.read()
    if len(file_data) > 32 * 1024:
        return {"message": "Comprovante deve ter no máximo 32 KB."}

    # Salva o comprovante (isso pode ser armazenado em uma pasta ou base de dados)
    os.makedirs("comprovantes", exist_ok=True)
    comprovante_path = os.path.join("comprovantes", comprovante.filename)
    with open(comprovante_path, "wb") as f:
        f.write(file_data)

    # Marca o número da rifa como vendido
    vendas_realizadas.append(numero_rifa)

    return {"message": f"Compra do bilhete {numero_rifa} realizada com sucesso!"}

# 👇 Adicionado para o Render reconhecer a porta corretamente
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

