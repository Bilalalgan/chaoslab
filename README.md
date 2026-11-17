# ChaosLab – Kaotik Sistem Analiz Laboratuvarı

N boyutlu (1–10) sürekli zamanlı (ODE) ve ayrık zamanlı (harita) doğrusal olmayan sistemlerin sembolik ve sayısal analizi için web uygulaması.

**Analizler:** faz portreleri, zaman serileri ve kelebek etkisi, denge/sabit noktalar ve Jacobian, Lyapunov spektrumu, Kaplan–Yorke boyutu, çatallaşma / yörünge diyagramı, Poincaré kesiti, çekim havzası, güç spektrumu, fraktal boyut (D₂, D₀), sistem karşılaştırma.
**Arayüz:** karanlık/aydınlık tema, Türkçe/İngilizce. Tüm kütüphaneler yerel (`static/vendor`), harici bağlantı yok.

## Yerel çalıştırma (Windows)

```
baslat.bat
```

veya

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn main:app --port 8000
```

Tarayıcı: http://127.0.0.1:8000

## Render

`render.yaml` hazır: Render → New → Blueprint → bu repo. Başlatma komutu `uvicorn main:app --host 0.0.0.0 --port $PORT`.

## Yapı

- `main.py` – FastAPI uçları
- `chaos_engine.py` – sürekli sistemler (SymPy + SciPy)
- `map_engine.py` – ayrık haritalar
- `analysis_tools.py` – spektrum, fraktal boyut, havza kümeleme
- `static/` – arayüz (`app.js`, `i18n.js`, `style.css`, `vendor/`)
