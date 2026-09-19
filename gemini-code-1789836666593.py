import os
import math
import requests
import numpy as np
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder=".")
CORS(app)

class MotorEstatisticoV2:
    def __init__(self, media_gols_liga_casa=1.5, media_gols_liga_fora=1.1):
        self.media_liga_casa = media_gols_liga_casa
        self.media_liga_fora = media_gols_liga_fora

    def _poisson_probability(self, k, lambd):
        return (math.pow(lambd, k) * math.exp(-lambd)) / math.factorial(k)

    def calcular_forca_times(self, stats_casa, stats_fora):
        ataque_casa_raw = (stats_casa.get('xg_pro_casa', 0) * 0.7) + (stats_casa.get('gols_pro_casa', 0) * 0.3)
        defesa_casa_raw = (stats_casa.get('xga_contra_casa', 0) * 0.7) + (stats_casa.get('gols_contra_casa', 0) * 0.3)

        ataque_fora_raw = (stats_fora.get('xg_pro_fora', 0) * 0.7) + (stats_fora.get('gols_pro_fora', 0) * 0.3)
        defesa_fora_raw = (stats_fora.get('xga_contra_fora', 0) * 0.7) + (stats_fora.get('gols_contra_fora', 0) * 0.3)

        forca_ataque_casa = ataque_casa_raw / self.media_liga_casa if self.media_liga_casa else 1
        forca_defesa_casa = defesa_casa_raw / self.media_liga_fora if self.media_liga_fora else 1
        forca_ataque_fora = ataque_fora_raw / self.media_liga_fora if self.media_liga_fora else 1
        forca_defesa_fora = defesa_fora_raw / self.media_liga_casa if self.media_liga_casa else 1

        xg_esperado_casa = forca_ataque_casa * forca_defesa_fora * self.media_liga_casa
        xg_esperado_fora = forca_ataque_fora * forca_defesa_casa * self.media_liga_fora

        return xg_esperado_casa, xg_esperado_fora

    def simular_partida(self, stats_casa, stats_fora, max_gols=6):
        xg_casa, xg_fora = self.calcular_forca_times(stats_casa, stats_fora)
        matriz_placar = np.zeros((max_gols, max_gols))

        for i in range(max_gols):
            prob_casa = self._poisson_probability(i, xg_casa)
            for j in range(max_gols):
                prob_fora = self._poisson_probability(j, xg_fora)
                matriz_placar[i][j] = prob_casa * prob_fora

        prob_vitoria_casa = float(np.sum(np.tril(matriz_placar, -1)))
        prob_empate = float(np.sum(np.diag(matriz_placar)))
        prob_vitoria_fora = float(np.sum(np.triu(matriz_placar, 1)))

        prob_over_1_5 = 0.0
        prob_over_2_5 = 0.0
        prob_btts = 0.0

        for i in range(max_gols):
            for j in range(max_gols):
                if (i + j) > 1.5:
                    prob_over_1_5 += matriz_placar[i][j]
                if (i + j) > 2.5:
                    prob_over_2_5 += matriz_placar[i][j]
                if i > 0 and j > 0:
                    prob_btts += matriz_placar[i][j]

        confianca = "ALTA" if (stats_casa.get('jogos_analisados', 0) >= 8 and stats_fora.get('jogos_analisados', 0) >= 8) else "MÉDIA"

        return {
            "xg_esperado": {
                "casa": round(xg_casa, 2),
                "fora": round(xg_fora, 2),
                "total": round(xg_casa + xg_fora, 2)
            },
            "probabilidades": {
                "vitoria_casa": round(prob_vitoria_casa * 100, 1),
                "empate": round(prob_empate * 100, 1),
                "vitoria_fora": round(prob_vitoria_fora * 100, 1),
                "over_1_5": round(prob_over_1_5 * 100, 1),
                "over_2_5": round(prob_over_2_5 * 100, 1),
                "btts": round(prob_btts * 100, 1)
            },
            "odds_justas": {
                "casa": round(1 / prob_vitoria_casa, 2) if prob_vitoria_casa > 0 else 0,
                "empate": round(1 / prob_empate, 2) if prob_empate > 0 else 0,
                "fora": round(1 / prob_vitoria_fora, 2) if prob_vitoria_fora > 0 else 0,
                "over_2_5": round(1 / prob_over_2_5, 2) if prob_over_2_5 > 0 else 0
            },
            "confianca_modelo": confianca
        }

motor = MotorEstatisticoV2()

@app.route("/")
def serve_index():
    return send_from_directory(".", "index.html")

@app.route("/api/analisar", methods=["POST"])
def analisar():
    data = request.json
    api_key = data.get("api_key")
    league_id = data.get("league_id", 71)
    season = data.get("season", 2024)
    team_casa_id = data.get("team_casa_id")
    team_fora_id = data.get("team_fora_id")

    url_base = "https://v3.football.api-sports.io/teams/statistics"
    headers = {"x-apisports-key": api_key}

    res_casa = requests.get(f"{url_base}?league={league_id}&season={season}&team={team_casa_id}", headers=headers).json()
    res_fora = requests.get(f"{url_base}?league={league_id}&season={season}&team={team_fora_id}", headers=headers).json()

    stats_c = res_casa.get("response", {})
    stats_f = res_fora.get("response", {})

    g_pro_c = float(stats_c.get("goals", {}).get("for", {}).get("average", {}).get("home") or 1.2)
    g_con_c = float(stats_c.get("goals", {}).get("against", {}).get("average", {}).get("home") or 1.0)
    g_pro_f = float(stats_f.get("goals", {}).get("for", {}).get("average", {}).get("away") or 1.0)
    g_con_f = float(stats_f.get("goals", {}).get("against", {}).get("average", {}).get("away") or 1.3)

    payload_casa = {
        "gols_pro_casa": g_pro_c,
        "gols_contra_casa": g_con_c,
        "xg_pro_casa": g_pro_c * 1.05,
        "xga_contra_casa": g_con_c * 0.95,
        "jogos_analisados": stats_c.get("fixtures", {}).get("played", {}).get("home", 10)
    }

    payload_fora = {
        "gols_pro_fora": g_pro_f,
        "gols_contra_fora": g_con_f,
        "xg_pro_fora": g_pro_f * 0.95,
        "xga_contra_fora": g_con_f * 1.05,
        "jogos_analisados": stats_f.get("fixtures", {}).get("played", {}).get("away", 10)
    }

    resultado = motor.simular_partida(payload_casa, payload_fora)
    return jsonify(resultado)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)