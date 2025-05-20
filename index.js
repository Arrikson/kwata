const functions = require("firebase-functions");
const admin = require("firebase-admin");
admin.initializeApp();
const db = admin.firestore();

exports.atualizarContadoresAoComprar = functions.firestore
    .document("rifas-compradas/{docId}")
    .onCreate(async (snap, context) => {
        const compradosSnapshot = await db.collection("rifas-compradas").get();
        const bilhetesComprados = compradosSnapshot.docs
            .map(doc => doc.data().bilhete)
            .filter(b => b !== undefined);

        const totalComprados = bilhetesComprados.length;

        const restantesSnapshot = await db.collection("rifas-restantes").limit(1).get();
        let bilhetesDisponiveis = [];

        if (!restantesSnapshot.empty) {
            const data = restantesSnapshot.docs[0].data();
            bilhetesDisponiveis = data.bilhetes_disponiveis || [];
        }

        const bilhetesSobrando = bilhetesDisponiveis.filter(b => !bilhetesComprados.includes(b));

        await db.collection("contadores").doc("resumo").set({
            total_comprados: totalComprados,
            bilhetes_sobrando: bilhetesSobrando,
            atualizado_em: admin.firestore.FieldValue.serverTimestamp()
        });

        console.log("Contadores atualizados automaticamente!");
        return null;
    });
