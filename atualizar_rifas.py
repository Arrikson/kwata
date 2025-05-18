import sys
import firebase_admin
from firebase_admin import credentials, firestore

# Verifica se foi fornecido o ID do produto
if len(sys.argv) != 2:
    print("Uso: python atualizar_rifas.py <ID_DO_PRODUTO>")
    sys.exit(1)

produto_id = sys.argv[1]

# Inicializa o Firebase Admin
try:
    firebase_admin.get_app()
except ValueError:
    cred = credentials.Certificate("firebase-service-account.json")  # Altere para seu arquivo .json
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Consulta o produto
produto_ref = db.collection('produtos').document(produto_id)
produto = produto_ref.get()

if not produto.exists:
    print(f"❌ Produto com ID '{produto_id}' não encontrado.")
    sys.exit(1)

dados = produto.to_dict()
total = int(dados.get('total_bilhetes', 0))
vendidos = int(dados.get('bilhetes_vendidos', 0))

disponiveis = total - vendidos
if disponiveis < 0:
    disponiveis = 0

# Atualiza o campo de bilhetes disponíveis
produto_ref.update({'bilhetes_disponiveis': disponiveis})
print(f"✅ Produto '{produto_id}' atualizado: {disponiveis} bilhetes disponíveis.")

